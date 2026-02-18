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

    # Create agent with the copy
    agent = create_pandas_dataframe_agent(
        llm,
        df,
        verbose=True,
        return_intermediate_steps=True,
        allow_dangerous_code=True,
        agent_type="tool-calling",
        prefix=(
            "Sos un analista de datos experto. Respondé en español. "
            "IMPORTANTE: La variable `df` contiene TODAS las filas del dataset. "
            "Lo que ves arriba es solo un preview. SIEMPRE usá `df` directamente, "
            "NUNCA hardcodees datos ni crees un DataFrame nuevo. "
            "Cuando te pidan un gráfico, usá matplotlib.pyplot. "
            "Siempre poné título y labels descriptivos en español. "
            "Usá plt.figure() antes de cada gráfico nuevo. "
            "NO modifiques el DataFrame original. Solo lectura."
        ),
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
