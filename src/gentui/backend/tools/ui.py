"""Generative-UI tools: "the tool call IS the UI".

The backend does almost nothing here. The widget spec IS the tool's arguments; the TUI
renders a widget from the TOOL_CALL_* events (see tui/widgets/table.py).
"""

from strands import tool

from gentui.backend.registry import register_tool


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
