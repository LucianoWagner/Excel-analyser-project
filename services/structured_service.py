"""
Structured query service — classifies user intent via LLM,
executes a safe predefined operation, and humanizes the result.
"""

import json
import logging
import re
from typing import Any, Callable

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from models import QueryResponse
from services.llm_service import get_llm
from services.chart_service import CHART_REGISTRY

logger = logging.getLogger(__name__)

# Type alias for operation executor functions
OperationExecutor = Callable[[pd.DataFrame, dict[str, Any]], str]

# ══════════════════════════════════════════════════
#  Intent Classification Prompt
# ══════════════════════════════════════════════════

SYSTEM_PROMPT = """\
Sos un clasificador de intenciones para consultas sobre un DataFrame de Pandas.
Dado un DataFrame con columnas: {columns}
Tipos de datos: {dtypes}

Clasificá la pregunta del usuario en UNA operación y extraé los parámetros.

OPERACIONES DISPONIBLES:
- count_rows: contar filas totales. Params: {{}}
- describe: estadísticas descriptivas generales (count, std, min, max, etc.). Params: {{"column": "nombre_col"}} (column es opcional). Usar solo si piden estadísticas generales o descriptivas.
- column_info: info sobre columnas. Params: {{}}
- value_counts: conteo de valores únicos. Params: {{"column": "nombre_col", "top_n": 10}}
- filter_count: contar filas con un filtro. Params: {{"column": "nombre_col", "operator": "==|!=|>|<|>=|<=|contains", "value": "valor"}}
- group_aggregate: calcular un agregado (promedio, suma, conteo, min, max, mediana) de una columna. Si piden "promedio de X", "suma de X", etc., usar ESTA operación. Params: {{"group_column": "col_o_null", "agg_column": "col", "function": "mean|sum|count|min|max|median"}}
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

HUMANIZE_PROMPT = """\
Sos un asistente amigable que responde consultas sobre datos.
El usuario hizo una pregunta y el sistema ya calculó el resultado.
Tu tarea es responder de forma clara, natural y en español.
Usá los datos que te doy para armar una respuesta conversacional.
Si hay números, resaltalos. Sé conciso pero informativo.
NO inventes datos que no estén en el resultado."""


# ══════════════════════════════════════════════════
#  Column Validation Helper
# ══════════════════════════════════════════════════

def _validate_column(df: pd.DataFrame, col: str | None, label: str = "Columna") -> str | None:
    """Return an error message if col is missing or not found, else None."""
    if not col:
        return f"{label} no especificada."
    if col not in df.columns:
        available = ", ".join(df.columns)
        return f"{label} '{col}' no encontrada. Disponibles: {available}"
    return None


# ══════════════════════════════════════════════════
#  Operation Executors
# ══════════════════════════════════════════════════

def _exec_count_rows(df: pd.DataFrame, params: dict[str, Any]) -> str:
    return f"El DataFrame tiene **{len(df)}** filas y **{len(df.columns)}** columnas."


def _exec_describe(df: pd.DataFrame, params: dict[str, Any]) -> str:
    col = params.get("column")
    if col and col in df.columns:
        desc = df[col].describe().to_string()
        return f"Estadísticas de **{col}**:\n```\n{desc}\n```"
    desc = df.describe(include="all").to_string()
    return f"Estadísticas descriptivas del DataFrame:\n```\n{desc}\n```"


def _exec_column_info(df: pd.DataFrame, params: dict[str, Any]) -> str:
    info_lines = [
        f"- **{col}**: tipo={df[col].dtype}, nulos={df[col].isnull().sum()}, únicos={df[col].nunique()}"
        for col in df.columns
    ]
    return "Información de columnas:\n" + "\n".join(info_lines)


def _exec_value_counts(df: pd.DataFrame, params: dict[str, Any]) -> str:
    col = params.get("column", "")
    if err := _validate_column(df, col):
        return err
    top_n = int(params.get("top_n", 10))
    counts = df[col].value_counts().head(top_n)
    return f"Conteo de valores en **{col}** (top {top_n}):\n```\n{counts.to_string()}\n```"


def _exec_filter_count(df: pd.DataFrame, params: dict[str, Any]) -> str:
    col = params.get("column", "")
    if err := _validate_column(df, col):
        return err

    op = params.get("operator", "==")
    value = params.get("value")

    try:
        if op == "contains":
            mask = df[col].astype(str).str.contains(str(value), case=False, na=False)
        else:
            # Cast value to column's type for proper comparison
            if pd.api.types.is_numeric_dtype(df[col].dtype):
                value = float(value) if "." in str(value) else int(value)

            operators = {
                "==": lambda v: df[col] == v,
                "!=": lambda v: df[col] != v,
                ">":  lambda v: df[col] > v,
                "<":  lambda v: df[col] < v,
                ">=": lambda v: df[col] >= v,
                "<=": lambda v: df[col] <= v,
            }
            if op not in operators:
                return f"Operador '{op}' no soportado. Opciones: ==, !=, >, <, >=, <=, contains"
            mask = operators[op](value)

        count = int(mask.sum())
        total = len(df)
        pct = round(count / total * 100, 1) if total > 0 else 0
        return f"Hay **{count}** filas ({pct}%) donde `{col} {op} {value}` (de {total} totales)."
    except (ValueError, TypeError) as e:
        return f"Error al filtrar: {e}"


def _exec_group_aggregate(df: pd.DataFrame, params: dict[str, Any]) -> str:
    group_col = params.get("group_column") or None
    agg_col = params.get("agg_column", "")
    func = params.get("function", "mean")

    if err := _validate_column(df, agg_col, "Columna de agregación"):
        return err

    valid_funcs = {"mean", "sum", "count", "min", "max", "median"}
    if func not in valid_funcs:
        return f"Función '{func}' no soportada. Opciones: {', '.join(sorted(valid_funcs))}"

    try:
        # No grouping → aggregate on the whole column
        if not group_col or group_col not in df.columns:
            result = df[agg_col].agg(func)
            if isinstance(result, float):
                result = round(result, 2)
            return f"**{func.upper()}** de `{agg_col}`: **{result}**"

        # Grouped aggregate
        result = df.groupby(group_col)[agg_col].agg(func)
        if result.dtype == float:
            result = result.round(2)
        return f"**{func.upper()}** de `{agg_col}` agrupado por `{group_col}`:\n```\n{result.to_string()}\n```"
    except Exception as e:
        return f"Error en la agregación: {e}"


def _exec_correlation(df: pd.DataFrame, params: dict[str, Any]) -> str:
    col_a = params.get("column_a", "")
    col_b = params.get("column_b", "")
    if err := _validate_column(df, col_a, "Columna A"):
        return err
    if err := _validate_column(df, col_b, "Columna B"):
        return err
    try:
        corr = df[col_a].corr(df[col_b])
        return f"La correlación entre **{col_a}** y **{col_b}** es: **{corr:.4f}**"
    except Exception as e:
        return f"Error al calcular correlación: {e}"


def _exec_unique_values(df: pd.DataFrame, params: dict[str, Any]) -> str:
    col = params.get("column", "")
    if err := _validate_column(df, col):
        return err
    uniques = df[col].dropna().unique()
    count = len(uniques)
    if count > 50:
        sample = ", ".join(str(v) for v in uniques[:50])
        return f"**{col}** tiene **{count}** valores únicos. Primeros 50: {sample}..."
    return f"Valores únicos en **{col}** ({count}):\n{', '.join(str(v) for v in sorted(uniques, key=str))}"


def _exec_top_bottom(df: pd.DataFrame, params: dict[str, Any]) -> str:
    col = params.get("column", "")
    if err := _validate_column(df, col):
        return err

    n = int(params.get("n", 1))
    ascending = bool(params.get("ascending", False))
    direction = "más bajos" if ascending else "más altos"

    try:
        result = df.nsmallest(n, col) if ascending else df.nlargest(n, col)
        return f"Top {n} filas con valores {direction} en **{col}**:\n```\n{result.to_string()}\n```"
    except TypeError as e:
        return f"Error: la columna '{col}' no es numérica. {e}"


# ══════════════════════════════════════════════════
#  Operation Registry
# ══════════════════════════════════════════════════

OPERATION_EXECUTORS: dict[str, OperationExecutor] = {
    "count_rows":      _exec_count_rows,
    "describe":        _exec_describe,
    "column_info":     _exec_column_info,
    "value_counts":    _exec_value_counts,
    "filter_count":    _exec_filter_count,
    "group_aggregate": _exec_group_aggregate,
    "correlation":     _exec_correlation,
    "unique_values":   _exec_unique_values,
    "top_bottom":      _exec_top_bottom,
}


# ══════════════════════════════════════════════════
#  JSON Parsing Helper
# ══════════════════════════════════════════════════

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Try extracting from code block first
    match = _JSON_BLOCK_RE.search(text)
    if match:
        return json.loads(match.group(1).strip())
    # Try parsing the raw text directly
    return json.loads(text.strip())


# ══════════════════════════════════════════════════
#  Main Entry Point
# ══════════════════════════════════════════════════

async def query_structured(df: pd.DataFrame, question: str) -> QueryResponse:
    """
    Classify user intent via LLM, execute the matching predefined operation,
    and humanize the result for a natural language response.
    """
    llm = get_llm()

    # Build context about the DataFrame
    columns_info = ", ".join(f"{col} ({df[col].dtype})" for col in df.columns)
    dtypes_info = df.dtypes.to_string()
    system_msg = SYSTEM_PROMPT.format(columns=columns_info, dtypes=dtypes_info)

    # ── Step 1: Classify intent ──
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=question),
        ])
        intent = _extract_json(response.content)
        operation = intent.get("operation", "unknown")
        params = intent.get("params", {})

    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for intent classification: %s", response.content[:200])
        return QueryResponse(
            answer="No pude entender la consulta. ¿Podés reformularla de otra manera?",
            mode="structured",
            operation_used="unknown",
        )
    except Exception as e:
        logger.error("Intent classification failed: %s", e)
        return QueryResponse(
            answer="Hubo un error al procesar la consulta. Intentá de nuevo.",
            mode="structured",
            operation_used="unknown",
        )

    logger.info("Structured query: '%s' -> operation=%s, params=%s", question[:80], operation, params)

    # ── Step 2: Handle unknown ──
    if operation == "unknown":
        return QueryResponse(
            answer="No pude clasificar tu consulta en una operación conocida. "
                   "Probá preguntar sobre: conteos, estadísticas, filtros, agrupaciones, o gráficos.",
            mode="structured",
            operation_used="unknown",
        )

    # ── Step 3: Handle chart operations ──
    if operation in CHART_REGISTRY:
        try:
            chart_base64 = CHART_REGISTRY[operation](df, **params)
            return QueryResponse(
                answer=f"Gráfico generado: **{operation.replace('_', ' ').title()}**",
                chart_base64=chart_base64,
                mode="structured",
                operation_used=operation,
            )
        except Exception as e:
            logger.warning("Chart generation failed for %s: %s", operation, e)
            return QueryResponse(
                answer=f"Error al generar el gráfico: {e}",
                mode="structured",
                operation_used=operation,
            )

    # ── Step 4: Handle data operations ──
    if operation in OPERATION_EXECUTORS:
        try:
            raw_answer = OPERATION_EXECUTORS[operation](df, params)
            logger.info("Raw answer: %s", raw_answer[:200])
            answer = await _humanize_response(llm, question, raw_answer)
            return QueryResponse(
                answer=answer,
                mode="structured",
                operation_used=operation,
            )
        except Exception as e:
            logger.error("Operation %s failed: %s", operation, e)
            return QueryResponse(
                answer=f"Error al ejecutar la operación: {e}",
                mode="structured",
                operation_used=operation,
            )

    # ── Fallback ──
    return QueryResponse(
        answer=f"Operación '{operation}' no reconocida.",
        mode="structured",
        operation_used=operation,
    )


# ══════════════════════════════════════════════════
#  Response Humanization
# ══════════════════════════════════════════════════

async def _humanize_response(llm, question: str, raw_data: str) -> str:
    """Use the LLM to convert raw data into a friendly, natural language response."""
    try:
        response = await llm.ainvoke([
            SystemMessage(content=HUMANIZE_PROMPT),
            HumanMessage(content=(
                f"Pregunta del usuario: {question}\n\n"
                f"Resultado del análisis:\n{raw_data}\n\n"
                "Respondé de forma natural y amigable:"
            )),
        ])
        return response.content.strip()
    except Exception:
        logger.warning("Humanization failed, returning raw data")
        return raw_data
