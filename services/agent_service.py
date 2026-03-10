"""
Agent service — executes queries using a LangChain Pandas Agent (admin mode).
Uses a SafePythonAstREPLTool that intercepts code BEFORE execution.
Detects DataFrame mutations and persists them to the session version history.
"""

import asyncio
from io import BytesIO
import base64
import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from langchain_experimental.tools import PythonAstREPLTool

from config import settings
from models import QueryResponse
from services.llm_service import get_llm
from utils.safety import check_code_safety, check_prompt_safety

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════
#  Safe Python REPL Tool — intercepts code BEFORE exec()
# ══════════════════════════════════════════════════

class SafePythonAstREPLTool(PythonAstREPLTool):
    """
    Drop-in replacement for PythonAstREPLTool that runs safety checks
    on the generated code BEFORE executing it.

    If dangerous patterns are detected, returns an error message to the LLM
    instead of executing. The LLM can then rewrite the code safely.
    Never executes dangerous code.
    """

    def _run(self, query: str, run_manager=None, **kwargs) -> str:
        """Override: check code safety before executing."""
        is_safe, violation = check_code_safety(query)
        if not is_safe:
            logger.warning("PRE-EXEC blocked: %s | Code: %s", violation, query[:200])
            return (
                f"SECURITY ERROR: {violation}. "
                "You MUST NOT use os, subprocess, exec, eval, open, pickle, requests, "
                "socket, shutil, or any system-level operations. "
                "Rewrite your code using only pandas, matplotlib, and seaborn."
            )
        return super()._run(query, run_manager=run_manager, **kwargs)


def _inject_safe_tool(agent) -> Optional["SafePythonAstREPLTool"]:
    """
    Replace the agent's PythonAstREPLTool with our SafePythonAstREPLTool.
    Returns the injected tool so we can inspect its locals after invocation.
    """
    for i, tool in enumerate(agent.tools):
        if isinstance(tool, PythonAstREPLTool) and not isinstance(tool, SafePythonAstREPLTool):
            safe_tool = SafePythonAstREPLTool(
                locals=tool.locals,
                globals=tool.globals,
                name=tool.name,
                description=tool.description,
            )
            agent.tools[i] = safe_tool
            logger.info("Injected SafePythonAstREPLTool into agent")
            return safe_tool
    logger.warning("Could not find PythonAstREPLTool to replace")
    return None


# ══════════════════════════════════════════════════
#  Chart & Code Extraction Helpers
# ══════════════════════════════════════════════════

def _capture_chart() -> str | None:
    """If matplotlib has an active figure with content, capture it as base64 PNG."""
    fig = plt.gcf()
    if fig.get_axes():
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
    plt.close("all")
    return None


def _extract_code(intermediate_steps: list) -> str | None:
    """Extract the Python code the agent generated from intermediate steps."""
    code_parts = []
    for step in intermediate_steps:
        if isinstance(step, tuple) and len(step) >= 2:
            action = step[0]
            if hasattr(action, "tool_input"):
                tool_input = action.tool_input
                if isinstance(tool_input, str):
                    code_parts.append(tool_input)
                elif isinstance(tool_input, dict) and "query" in tool_input:
                    code_parts.append(tool_input["query"])
    return "\n".join(code_parts) if code_parts else None


def _detect_mutation(
    df_before: pd.DataFrame,
    safe_tool: Optional[SafePythonAstREPLTool],
) -> Optional[pd.DataFrame]:
    """
    Check if the agent mutated the DataFrame during execution.
    Compares df_before with the df currently in the tool's locals.
    Returns the mutated df if different, None otherwise.
    """
    if safe_tool is None:
        return None

    df_after = safe_tool.locals.get("df")
    if df_after is None or not isinstance(df_after, pd.DataFrame):
        return None

    # Shape change → definitely mutated
    if df_before.shape != df_after.shape:
        return df_after

    # Content change (compare values, handle NaN equality)
    try:
        if not df_before.equals(df_after):
            return df_after
    except Exception:
        pass  # If comparison fails, assume no mutation

    return None


# ══════════════════════════════════════════════════
#  Main Entry Point
# ══════════════════════════════════════════════════

async def query_with_agent(
    df: pd.DataFrame,
    question: str,
    session_id: str,
    sheet_name: str,
) -> QueryResponse:
    """
    Execute a query using the LangChain Pandas Agent.
    Detects DataFrame mutations and saves them as new versions in the session.

    Security layers:
        1. Prompt injection check (before LLM sees the question)
        2. Pre-execution code check (SafePythonAstREPLTool — before exec)
    """
    llm = get_llm()

    # ── Safety Layer 1: Check user question for prompt injection ──
    is_safe, violation = check_prompt_safety(question)
    if not is_safe:
        logger.warning("Prompt injection blocked: '%s'", question[:100])
        return QueryResponse(
            answer="⚠️ Tu consulta fue bloqueada por contener patrones sospechosos. "
                   "Reformulá la pregunta de manera más natural.",
            mode="agent",
        )

    # Clear any existing matplotlib figures
    plt.close("all")

    # Snapshot of the df before agent runs (for mutation detection)
    df_snapshot = df.copy(deep=True)

    # Build a description of the dataframe for context
    df_info = (
        f"La variable `df` ya existe y contiene {len(df)} filas y {len(df.columns)} columnas.\n"
        f"Columnas: {list(df.columns)}\n"
        f"Tipos: {df.dtypes.to_dict()}\n"
        f"Primeras 3 filas de ejemplo:\n{df.head(3).to_string()}\n\n"
        "REGLAS OBLIGATORIAS:\n"
        "1. SIEMPRE usa la variable `df` que ya existe. NUNCA crees un DataFrame nuevo.\n"
        "2. `df` tiene TODAS las filas (no solo las de ejemplo).\n"
        "3. NUNCA uses pd.DataFrame({...}) para crear datos.\n"
        "4. Responde en español.\n"
        "5. NUNCA uses os, subprocess, exec, eval, open, pickle, requests, socket ni shutil.\n"
    )

    # Create agent
    agent = create_pandas_dataframe_agent(
        llm,
        df,
        verbose=True,
        return_intermediate_steps=True,
        allow_dangerous_code=True,
        agent_type="tool-calling",
        include_df_in_prompt=False,
        prefix=df_info,
        suffix=(
            "Recordá: NUNCA crees un DataFrame nuevo con pd.DataFrame(). "
            "Usá SIEMPRE la variable `df` que tiene las {len_df} filas completas. "
            "Cuando te pidan un gráfico, usá plt.figure() antes."
        ).format(len_df=len(df)),
    )

    # ── Safety Layer 2: Inject safe tool (pre-execution check) ──
    safe_tool = _inject_safe_tool(agent)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(agent.invoke, {"input": question}),
            timeout=settings.query_timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"La consulta excedió el tiempo máximo de {settings.query_timeout_seconds}s. "
            "Intentá con una pregunta más simple."
        )

    # Extract answer and code
    answer = result.get("output", "No se pudo generar una respuesta.")
    intermediate_steps = result.get("intermediate_steps", [])
    code_generated = _extract_code(intermediate_steps)

    # ── Mutation detection: save new version if df was modified ──
    mutated_df = _detect_mutation(df_snapshot, safe_tool)
    version_saved = False
    if mutated_df is not None:
        # Import here to avoid circular imports
        from services.excel_service import save_version
        save_version(session_id, sheet_name, mutated_df)
        version_saved = True
        logger.info("Mutation detected — new version saved for session %s, sheet=%s",
                    session_id[:8], sheet_name)

    # Capture chart if one was generated
    chart_base64 = _capture_chart()

    logger.info("Agent query: '%s...' | Code: %s | Chart: %s | VersionSaved: %s",
                question[:80], bool(code_generated), bool(chart_base64), version_saved)

    return QueryResponse(
        answer=answer,
        chart_base64=chart_base64,
        code_generated=code_generated,
        mode="agent",
    )
