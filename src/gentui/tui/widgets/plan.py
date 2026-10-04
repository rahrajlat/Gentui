"""Plan widget: a live checklist bound to the shared `plan` state (not to tool args)."""

from typing import Any

from rich.text import Text

from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

ICON = {"pending": ("☐", "dim"), "in_progress": ("◐", "bold yellow"), "completed": ("✔", "green")}


@register_widget("todo_write")
class PlanWidget(ToolWidget):
    """The harness's `todo_write` tool changes backend state; the backend then emits
    STATE_SNAPSHOT / STATE_DELTA and the app calls `set_plan`. One widget, updated in place."""

    singleton = True
    DEFAULT_CSS = "PlanWidget { border: none; border-left: thick $warning 60%; }"

    def on_start(self) -> None:
        self.show(Text("☰ Planning…", style="dim italic"))

    def set_plan(self, plan: list[dict[str, Any]]) -> None:
        done = sum(1 for item in plan if item["status"] == "completed")
        text = Text(f"☰ Plan  {done}/{len(plan)}\n", style="bold")
        for item in plan:
            icon, style = ICON.get(item["status"], ICON["pending"])
            line_style = "strike dim" if item["status"] == "completed" else style
            text.append(f"{icon} ", style=style)
            text.append(item["content"] + "\n", style=line_style if item["status"] != "pending" else "")
        text.rstrip()
        self.show(text)
