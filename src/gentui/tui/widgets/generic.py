"""Fallback widgets: a JSON card for unknown tools, and a quiet one-liner for plumbing tools."""

import json
from typing import Any

from rich.console import Group
from rich.json import JSON
from rich.text import Text

from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget


class GenericToolWidget(ToolWidget):
    """Any tool without a dedicated widget: show its name, args and result as JSON."""

    def on_start(self) -> None:
        self._draw(None)

    def on_args(self, args: dict[str, Any]) -> None:
        super().on_args(args)
        self._draw(None)

    def on_end(self, args: dict[str, Any]) -> None:
        super().on_end(args)
        self._draw(None)

    def on_result(self, text: str) -> None:
        self._draw(text)

    def _draw(self, result: str | None) -> None:
        parts: list[Any] = [Text(f"⚙ {self.tool_name}", style="bold")]
        parts.append(JSON(json.dumps(self.args)) if self.args else Text("…", style="dim"))
        if result is not None:
            parts.append(Text(result[:600], style="dim"))
        self.show(Group(*parts))


@register_widget("shell_agent")
class ActivityWidget(ToolWidget):
    """The orchestrator delegating to a sub-agent: just a dim status line, no border."""

    DEFAULT_CSS = """
    ActivityWidget { border: none; margin: 0; padding: 0 1; color: $text-muted; }
    """

    def on_start(self) -> None:
        self.show(Text("🐚 asking the shell agent…", style="dim italic"))

    def on_result(self, text: str) -> None:
        self.show(Text(f"🐚 {text.strip()}", style="dim"))
