"""Fallback widgets: a JSON card for unknown tools, and a quiet one-liner for plumbing tools."""

import json
from typing import Any

from rich.console import Group
from rich.text import Text

from gentui.tui.branding import RESULT_MARK, TOOL_MARK
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
        head = Text.assemble((f"{TOOL_MARK} ", "bold"), (self.tool_name, "bold"))
        if self.args:
            summary = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in self.args.items())
            head.append(f"({summary[:90] + '…' if len(summary) > 90 else summary})", style="dim")
        parts: list[Any] = [head]
        if result is not None:
            first = next((line for line in result.strip().splitlines() if line.strip()), "(no output)")
            more = len(result.strip().splitlines()) - 1
            tail = f"  (+{more} lines)" if more > 0 else ""
            parts.append(Text(f"  {RESULT_MARK}  {first[:110]}{tail}", style="dim"))
        self.show(Group(*parts))


@register_widget("shell_agent")
class ActivityWidget(ToolWidget):
    """The orchestrator delegating to a sub-agent: just a dim status line, no border."""

    DEFAULT_CSS = """
    ActivityWidget { border: none; margin: 0; padding: 0 1; color: $text-muted; }
    """

    def on_start(self) -> None:
        self.show(Text("$ asking the shell agent…", style="dim italic"))

    def on_result(self, text: str) -> None:
        self.show(Text(f"$ {text.strip()}", style="dim"))


@register_widget("search_memory")
class MemoryWidget(ToolWidget):
    """The agent consulting its long-term memory: a dim one-liner instead of a JSON card."""

    DEFAULT_CSS = """
    MemoryWidget { border: none; margin: 0; padding: 0 1; color: $text-muted; }
    """

    def _query(self) -> str:
        return str(self.args.get("query", "")).strip()

    def on_start(self) -> None:
        self.show(Text("◌ recalling…", style="dim italic"))

    def on_end(self, args: dict[str, Any]) -> None:
        super().on_end(args)
        self.show(Text(f"◌ recalling “{self._query()}”…", style="dim italic"))

    def on_result(self, text: str) -> None:
        found = bool(text.strip()) and text.strip() not in ("[]", "{}", "null")
        self.show(Text(f"◌ recalled “{self._query()}”" if found else f"◌ nothing remembered for “{self._query()}”", style="dim"))
