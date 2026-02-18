import json
import logging

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from models import QueryResponse
from services.llm_service import get_llm
from services.chart_service import CHART_REGISTRY

logger = logging.getLogger(__name__)

# ── System prompt for intent classification ──
SYSTEM_PROMPT = """Sos un clasificador de intenciones para consultas sobre un DataFrame de Pandas.
Dado un DataFrame con las siguientes columnas: {columns}
Y tipos de datos: {dtypes}

Tu tarea es clasificar la pregunta del usuario en UNA de estas operaciones y extraer los parámetros.

OPERACIONES DISPONIBLES:
- count_rows: contar filas totales. Params: {{}}
- describe: estadísticas descriptivas. Params: {{"column": "nombre_col"}} (column es opcional)
- column_info: info sobre columnas. Params: {{}}
- value_counts: conteo de valores únicos. Params: {{"column": "nombre_col", "top_n": 10}}
- filter_count: contar filas con un filtro. Params: {{"column": "nombre_col", "operator": "==|!=|>|<|>=|<=|contains", "value": "valor"}}
- group_aggregate: agrupar y agregar. Params: {{"group_column": "col", "agg_column": "col", "function": "mean|sum|count|min|max|median"}}
- correlation: correlación entre columnas. Params: {{"column_a": "col", "column_b": "col"}}
- unique_values: valores únicos de columna. Params: {{"column": "nombre_col"}}
- top_bottom: encontrar filas con valores más altos o bajos. Params: {{"column": "nombre_col", "n": 1, "ascending": false}}
- bar_chart: gráfico de barras. Params: {{"column": "nombre_col", "top_n": 15, "horizontal": false}}
- histogram: histograma. Params: {{"column": "nombre_col", "bins": 20}}
- pie_chart: gráfico de torta. Params: {{"column": "nombre_col", "top_n": 8}}
- scatter_plot: gráfico de dispersión. Params: {{"x_column": "col", "y_column": "col", "color_by": null}}
- box_plot: box plot. Params: {{"column": "nombre_col", "group_by": null}}
- line_chart: gráfico de línea. Params: {{"x_column": "col", "y_column": "col", "group_by": null}}
- heatmap: heatmap de correlación. Params: {{"columns": null}}
- unknown: no se puede clasificar. Params: {{}}

Respondé ÚNICAMENTE con JSON válido, sin explicaciones ni markdown:
{{"operation": "nombre_operacion", "params": {{...}}}}
"""


# ── Operation executors ──

def _exec_count_rows(df: pd.DataFrame, params: dict) -> str:
    return f"El DataFrame tiene **{len(df)}** filas y **{len(df.columns)}** columnas."


def _exec_describe(df: pd.DataFrame, params: dict) -> str:
    col = params.get("column")
    if col and col in df.columns:
        desc = df[col].describe().to_string()
        return f"Estadísticas de **{col}**:\n```\n{desc}\n```"
    desc = df.describe(include="all").to_string()
    return f"Estadísticas descriptivas del DataFrame:\n```\n{desc}\n```"


def _exec_column_info(df: pd.DataFrame, params: dict) -> str:
    info_lines = []
    for col in df.columns:
        dtype = df[col].dtype
        nulls = df[col].isnull().sum()
        unique = df[col].nunique()
        info_lines.append(f"- **{col}**: tipo={dtype}, nulos={nulls}, únicos={unique}")
    return "Información de columnas:\n" + "\n".join(info_lines)


def _exec_value_counts(df: pd.DataFrame, params: dict) -> str:
    col = params.get("column", "")
    if col not in df.columns:
        return f"Columna '{col}' no encontrada. Columnas disponibles: {', '.join(df.columns)}"
    top_n = params.get("top_n", 10)
    counts = df[col].value_counts().head(top_n)
    result = counts.to_string()
    return f"Conteo de valores en **{col}** (top {top_n}):\n```\n{result}\n```"


def _exec_filter_count(df: pd.DataFrame, params: dict) -> str:
    col = params.get("column", "")
    if col not in df.columns:
        return f"Columna '{col}' no encontrada."
    op = params.get("operator", "==")
    value = params.get("value")

    try:
        if op == "contains":
            mask = df[col].astype(str).str.contains(str(value), case=False, na=False)
        else:
            # Try to cast value to the column's type
            col_dtype = df[col].dtype
            if pd.api.types.is_numeric_dtype(col_dtype):
                value = float(value) if "." in str(value) else int(value)

            ops = {
                "==": lambda: df[col] == value,
                "!=": lambda: df[col] != value,
                ">": lambda: df[col] > value,
                "<": lambda: df[col] < value,
                ">=": lambda: df[col] >= value,
                "<=": lambda: df[col] <= value,
            }
            if op not in ops:
                return f"Operador '{op}' no soportado. Opciones: ==, !=, >, <, >=, <=, contains"
            mask = ops[op]()

        count = mask.sum()
        return f"Hay **{count}** filas donde `{col} {op} {value}`."
    except Exception as e:
        return f"Error al filtrar: {str(e)}"


def _exec_group_aggregate(df: pd.DataFrame, params: dict) -> str:
    group_col = params.get("group_column", "")
    agg_col = params.get("agg_column", "")
    func = params.get("function", "mean")

    if group_col not in df.columns:
        return f"Columna de agrupación '{group_col}' no encontrada."
    if agg_col not in df.columns:
        return f"Columna de agregación '{agg_col}' no encontrada."

    try:
        result = df.groupby(group_col)[agg_col].agg(func)
        return f"**{func.upper()}** de `{agg_col}` agrupado por `{group_col}`:\n```\n{result.to_string()}\n```"
    except Exception as e:
        return f"Error en la agregación: {str(e)}"


def _exec_correlation(df: pd.DataFrame, params: dict) -> str:
    col_a = params.get("column_a", "")
    col_b = params.get("column_b", "")
    if col_a not in df.columns or col_b not in df.columns:
        return f"Columnas no encontradas. Disponibles: {', '.join(df.columns)}"
    try:
        corr = df[col_a].corr(df[col_b])
        return f"La correlación entre **{col_a}** y **{col_b}** es: **{corr:.4f}**"
    except Exception as e:
        return f"Error al calcular correlación: {str(e)}"


def _exec_unique_values(df: pd.DataFrame, params: dict) -> str:
    col = params.get("column", "")
    if col not in df.columns:
        return f"Columna '{col}' no encontrada."
    uniques = df[col].dropna().unique()
    if len(uniques) > 50:
        sample = ", ".join(str(v) for v in uniques[:50])
        return f"**{col}** tiene **{len(uniques)}** valores únicos. Primeros 50: {sample}..."
    return f"Valores únicos en **{col}** ({len(uniques)}):\n{', '.join(str(v) for v in uniques)}"


def _exec_top_bottom(df: pd.DataFrame, params: dict) -> str:
    col = params.get("column", "")
    if col not in df.columns:
        return f"Columna '{col}' no encontrada."
    n = params.get("n", 1)
    ascending = params.get("ascending", False)
    direction = "más bajos" if ascending else "más altos"
    try:
        result = df.nlargest(n, col) if not ascending else df.nsmallest(n, col)
        return f"Top {n} filas con valores {direction} en **{col}**:\n```\n{result.to_string()}\n```"
    except Exception as e:
        return f"Error: {str(e)}"


# ── Operation registry ──
OPERATION_EXECUTORS = {
    "count_rows": _exec_count_rows,
    "describe": _exec_describe,
    "column_info": _exec_column_info,
    "value_counts": _exec_value_counts,
    "filter_count": _exec_filter_count,
    "group_aggregate": _exec_group_aggregate,
    "correlation": _exec_correlation,
    "unique_values": _exec_unique_values,
    "top_bottom": _exec_top_bottom,
}


async def query_structured(df: pd.DataFrame, question: str) -> QueryResponse:
    """
    Classify user intent via LLM, then execute the matching predefined operation.
    """
    llm = get_llm()

    # Build context about the DataFrame
    columns_info = ", ".join(f"{col} ({df[col].dtype})" for col in df.columns)
    dtypes_info = df.dtypes.to_string()

    system_msg = SYSTEM_PROMPT.format(columns=columns_info, dtypes=dtypes_info)

    # Ask LLM to classify
    messages = [
        SystemMessage(content=system_msg),
        HumanMessage(content=question),
    ]

    try:
        response = await llm.ainvoke(messages)
        raw_response = response.content.strip()

        # Parse JSON from the LLM response
        # Handle cases where LLM wraps in ```json ... ```
        if "```" in raw_response:
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
            raw_response = raw_response.strip()

        intent = json.loads(raw_response)
        operation = intent.get("operation", "unknown")
        params = intent.get("params", {})

    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to classify intent: {e}. Raw: {raw_response if 'raw_response' in dir() else 'N/A'}")
        return QueryResponse(
            answer="No pude entender la consulta. ¿Podés reformularla de otra manera?",
            mode="structured",
            operation_used="unknown",
        )

    logger.info(f"Structured query: '{question[:80]}' → operation={operation}, params={params}")

    # Handle unknown
    if operation == "unknown":
        return QueryResponse(
            answer="No pude clasificar tu consulta en una operación conocida. "
                   "Probá preguntar sobre: conteos, estadísticas, filtros, agrupaciones, o gráficos.",
            mode="structured",
            operation_used="unknown",
        )

    # Handle chart operations
    if operation in CHART_REGISTRY:
        try:
            chart_func = CHART_REGISTRY[operation]
            chart_base64 = chart_func(df, **params)
            return QueryResponse(
                answer=f"Gráfico generado: **{operation.replace('_', ' ').title()}**",
                chart_base64=chart_base64,
                mode="structured",
                operation_used=operation,
            )
        except Exception as e:
            return QueryResponse(
                answer=f"Error al generar el gráfico: {str(e)}",
                mode="structured",
                operation_used=operation,
            )

    # Handle data operations
    if operation in OPERATION_EXECUTORS:
        try:
            raw_answer = OPERATION_EXECUTORS[operation](df, params)
            logger.info(f"Raw answer: {raw_answer}")
            # Humanize the raw result through LLM
            answer = await _humanize_response(llm, question, raw_answer)
            return QueryResponse(
                answer=answer,
                mode="structured",
                operation_used=operation,
            )
        except Exception as e:
            return QueryResponse(
                answer=f"Error al ejecutar la operación: {str(e)}",
                mode="structured",
                operation_used=operation,
            )

    # Fallback
    return QueryResponse(
        answer=f"Operación '{operation}' no reconocida.",
        mode="structured",
        operation_used=operation,
    )


async def _humanize_response(llm, question: str, raw_data: str) -> str:
    """Use the LLM to convert raw data into a friendly, natural language response."""
    messages = [
        SystemMessage(content=(
            "Sos un asistente amigable que responde consultas sobre datos. "
            "El usuario hizo una pregunta y el sistema ya calculó el resultado. "
            "Tu tarea es responder de forma clara, natural y en español. "
            "Usá los datos que te doy para armar una respuesta conversacional. "
            "Si hay números, resaltalos. Sé conciso pero informativo. "
            "NO inventes datos que no estén en el resultado."
        )),
        HumanMessage(content=(
            f"Pregunta del usuario: {question}\n\n"
            f"Resultado del análisis:\n{raw_data}\n\n"
            "Respondé de forma natural y amigable:"
        )),
    ]
    try:
        response = await llm.ainvoke(messages)
        return response.content.strip()
    except Exception:
        # If humanization fails, return raw data
        return raw_data
