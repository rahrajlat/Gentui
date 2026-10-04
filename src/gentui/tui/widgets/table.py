"""Table widget: renders the `show_table` tool call (the args ARE the widget spec)."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import DataTable, Static

from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget


@register_widget("show_table")
class TableWidget(ToolWidget):
    DEFAULT_CSS = """
    TableWidget { border: round $secondary 60%; }
    TableWidget DataTable { height: auto; max-height: 20; }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="body")
        yield DataTable(id="table", zebra_stripes=True, cursor_type="row")

    def on_start(self) -> None:
        self.show(Text("📊 Building a table…", style="dim italic"))  # skeleton

    def on_end(self, args: dict[str, Any]) -> None:
        super().on_end(args)
        self.show(Text(f"📊 {args.get('title', 'Table')}", style="bold"))
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns(*[str(c) for c in args.get("columns", [])])
        for row in args.get("rows", [])[:100]:
            table.add_row(*[str(cell) for cell in row])
