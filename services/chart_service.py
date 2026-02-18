from io import BytesIO
import base64

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd


def _fig_to_base64(fig) -> str:
    """Convert a matplotlib figure to a base64 PNG string."""
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _validate_column(df: pd.DataFrame, column: str) -> None:
    """Raise ValueError if column doesn't exist in DataFrame."""
    if column not in df.columns:
        available = ", ".join(df.columns.astype(str))
        raise ValueError(f"Columna '{column}' no encontrada. Columnas disponibles: {available}")


def bar_chart(df: pd.DataFrame, column: str, top_n: int = 15, horizontal: bool = False) -> str:
    """Bar chart showing value counts for a column. Returns base64 PNG."""
    _validate_column(df, column)
    counts = df[column].value_counts().head(top_n)

    fig, ax = plt.subplots(figsize=(10, 6))
    kind = "barh" if horizontal else "bar"
    counts.plot(kind=kind, ax=ax, color="#6366F1", edgecolor="white")
    ax.set_title(f"Conteo por {column}", fontsize=14, fontweight="bold")
    ax.set_ylabel("Conteo" if not horizontal else column)
    ax.set_xlabel(column if not horizontal else "Conteo")
    plt.xticks(rotation=45, ha="right") if not horizontal else None
    plt.tight_layout()
    return _fig_to_base64(fig)


def histogram(df: pd.DataFrame, column: str, bins: int = 20) -> str:
    """Histogram for a numeric column. Returns base64 PNG."""
    _validate_column(df, column)
    fig, ax = plt.subplots(figsize=(10, 6))
    df[column].dropna().plot(kind="hist", bins=bins, ax=ax, color="#8B5CF6", edgecolor="white")
    ax.set_title(f"Distribución de {column}", fontsize=14, fontweight="bold")
    ax.set_xlabel(column)
    ax.set_ylabel("Frecuencia")
    plt.tight_layout()
    return _fig_to_base64(fig)


def pie_chart(df: pd.DataFrame, column: str, top_n: int = 8) -> str:
    """Pie chart with percentages. Returns base64 PNG."""
    _validate_column(df, column)
    counts = df[column].value_counts().head(top_n)

    fig, ax = plt.subplots(figsize=(8, 8))
    colors = sns.color_palette("husl", len(counts))
    counts.plot(kind="pie", ax=ax, autopct="%1.1f%%", colors=colors, startangle=90)
    ax.set_title(f"Distribución por {column}", fontsize=14, fontweight="bold")
    ax.set_ylabel("")
    plt.tight_layout()
    return _fig_to_base64(fig)


def scatter_plot(df: pd.DataFrame, x_column: str, y_column: str, color_by: str = None) -> str:
    """Scatter plot between two numeric columns. Returns base64 PNG."""
    _validate_column(df, x_column)
    _validate_column(df, y_column)

    fig, ax = plt.subplots(figsize=(10, 6))
    if color_by and color_by in df.columns:
        for group, group_df in df.groupby(color_by):
            ax.scatter(group_df[x_column], group_df[y_column], label=str(group), alpha=0.7, s=40)
        ax.legend(title=color_by, bbox_to_anchor=(1.05, 1), loc="upper left")
    else:
        ax.scatter(df[x_column], df[y_column], color="#6366F1", alpha=0.7, s=40)

    ax.set_title(f"{x_column} vs {y_column}", fontsize=14, fontweight="bold")
    ax.set_xlabel(x_column)
    ax.set_ylabel(y_column)
    plt.tight_layout()
    return _fig_to_base64(fig)


def box_plot(df: pd.DataFrame, column: str, group_by: str = None) -> str:
    """Box plot for distribution and outliers. Returns base64 PNG."""
    _validate_column(df, column)

    fig, ax = plt.subplots(figsize=(10, 6))
    if group_by and group_by in df.columns:
        df.boxplot(column=column, by=group_by, ax=ax)
        ax.set_title(f"{column} por {group_by}", fontsize=14, fontweight="bold")
        plt.suptitle("")  # Remove auto-title
    else:
        df[[column]].boxplot(ax=ax)
        ax.set_title(f"Box plot de {column}", fontsize=14, fontweight="bold")
    plt.tight_layout()
    return _fig_to_base64(fig)


def line_chart(df: pd.DataFrame, x_column: str, y_column: str, group_by: str = None) -> str:
    """Line chart. Returns base64 PNG."""
    _validate_column(df, x_column)
    _validate_column(df, y_column)

    fig, ax = plt.subplots(figsize=(10, 6))
    if group_by and group_by in df.columns:
        for group, group_df in df.groupby(group_by):
            group_df_sorted = group_df.sort_values(x_column)
            ax.plot(group_df_sorted[x_column], group_df_sorted[y_column], label=str(group), marker="o", markersize=4)
        ax.legend(title=group_by)
    else:
        df_sorted = df.sort_values(x_column)
        ax.plot(df_sorted[x_column], df_sorted[y_column], color="#6366F1", marker="o", markersize=4)

    ax.set_title(f"{y_column} vs {x_column}", fontsize=14, fontweight="bold")
    ax.set_xlabel(x_column)
    ax.set_ylabel(y_column)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    return _fig_to_base64(fig)


def heatmap(df: pd.DataFrame, columns: list[str] = None) -> str:
    """Correlation heatmap for numeric columns. Returns base64 PNG."""
    numeric_df = df.select_dtypes(include="number")
    if columns:
        valid_cols = [c for c in columns if c in numeric_df.columns]
        if valid_cols:
            numeric_df = numeric_df[valid_cols]

    if numeric_df.empty or len(numeric_df.columns) < 2:
        raise ValueError("Se necesitan al menos 2 columnas numéricas para un heatmap de correlación")

    corr = numeric_df.corr()
    fig, ax = plt.subplots(figsize=(10, 8))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdYlBu_r", center=0, ax=ax, square=True)
    ax.set_title("Mapa de Correlación", fontsize=14, fontweight="bold")
    plt.tight_layout()
    return _fig_to_base64(fig)


# ── Registry for easy lookup ──
CHART_REGISTRY = {
    "bar_chart": bar_chart,
    "histogram": histogram,
    "pie_chart": pie_chart,
    "scatter_plot": scatter_plot,
    "box_plot": box_plot,
    "line_chart": line_chart,
    "heatmap": heatmap,
}
