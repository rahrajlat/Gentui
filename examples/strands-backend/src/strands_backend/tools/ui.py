"""Generative-UI tools: "the tool call IS the UI".

The backend does almost nothing here. The widget spec IS the tool's arguments; the TUI
renders a widget from the TOOL_CALL_* events (see tui/widgets/table.py).
"""

from strands import tool

from strands_backend.registry import register_tool


@register_tool
@tool
def show_table(title: str, columns: list[str], rows: list[list[str]]) -> str:
    """Show the user a table. Use it whenever presenting several items with several attributes.

    Args:
        title: Short heading for the table.
        columns: Column headers.
        rows: One list of cell strings per row, in the same order as `columns`.
    """
    return f"Table '{title}' with {len(rows)} rows shown to the user."


@register_tool
@tool
def show_chart(
    type: str,
    title: str,
    series: list[dict],
    x: list | None = None,
    x_label: str = "",
    y_label: str = "",
    bins: int = 10,
) -> str:
    """Draw a chart for the user. Use it for numeric data: trends, comparisons, distributions.

    Args:
        type: "line", "bar", "scatter" or "histogram".
        title: Short heading.
        series: One dict per line/bar group: {"name": "label", "values": [numbers]}.
            A histogram uses only the first series' values.
        x: X values (numbers) or category labels, same length as each series' values.
            Omit for a histogram.
        x_label: Optional x axis title.
        y_label: Optional y axis title.
        bins: Number of histogram bins.
    """
    return f"Chart '{title}' ({type}) shown to the user."
