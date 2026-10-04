"""Output widget: shows a command while it runs and its output when finished."""

import json
from typing import Any

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget


@register_widget("run_command")
class OutputWidget(ToolWidget):
    DEFAULT_CSS = """
    OutputWidget { border: none; border-left: thick $success 60%; }
    OutputWidget #scroll { height: auto; max-height: 16; }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="body")
        with VerticalScroll(id="scroll"):
            yield Static(id="output")

    command = "approved command"  # run_command only gets an approval_id; the result carries the command

    def _header(self, badge: Text | None = None) -> Text:
        header = Text.assemble(("▶ ", "bold green"), (self.command, "bold"))
        return header + Text("  ") + badge if badge else header

    def on_start(self) -> None:
        self.show(Text("◔ Preparing to run…", style="dim italic"))

    def on_args(self, args: dict[str, Any]) -> None:
        super().on_args(args)
        self.show(Group(self._header(), Text("running…", style="dim italic")))

    def on_result(self, text: str) -> None:
        try:
            result = json.loads(text)
        except json.JSONDecodeError:  # REFUSED: ... or an error string
            self.show(Group(self._header(), Text(text, style="bold red")))
            return
        self.command = result.get("command", self.command)
        if result.get("timed_out"):
            badge = Text(" TIMED OUT ", style="bold black on red")
        else:
            code = result.get("exit_code")
            badge = Text(f" exit {code} ", style=f"bold black on {'green' if code == 0 else 'red'}")
        self.show(self._header(badge))
        output = result.get("output", "").rstrip() or "(no output)"
        if result.get("truncated"):
            output += "\n… output truncated"
        self.query_one("#output", Static).update(Text(output))
