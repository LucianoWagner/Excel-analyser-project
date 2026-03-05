import asyncio
from io import BytesIO
import base64
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent

from config import settings
from models import QueryResponse
from services.llm_service import get_llm

logger = logging.getLogger(__name__)


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


async def query_with_agent(df: pd.DataFrame, question: str) -> QueryResponse:
    """
    Execute a query using the LangChain Pandas Agent.
    The agent generates and runs Python code on a COPY of the DataFrame.
    Returns the answer, any generated chart, and the code used.
    """
    llm = get_llm()

    # Clear any existing matplotlib figures
    plt.close("all")

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
    )

    # Create agent with the copy
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

    # Extract answer
    answer = result.get("output", "No se pudo generar una respuesta.")

    # Extract generated code
    intermediate_steps = result.get("intermediate_steps", [])
    code_generated = _extract_code(intermediate_steps)

    # Capture chart if one was generated
    chart_base64 = _capture_chart()

    logger.info(f"Agent query: '{question[:80]}...' | Code: {bool(code_generated)} | Chart: {bool(chart_base64)}")

    return QueryResponse(
        answer=answer,
        chart_base64=chart_base64,
        code_generated=code_generated,
        mode="agent",
    )
