"""Generic prompt for an AG-UI interrupt that no tool widget claims (confirmation, input needed)."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static

from gentui.tui.widgets.base import ToolWidget


def asks_for_approval(schema: dict[str, Any] | None) -> bool:
    """True if the interrupt's responseSchema is just {approved: boolean} (or has no schema)."""
    if not schema:
        return True
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    return props.get("approved", {}).get("type") == "boolean" and required <= {"approved"}


class InterruptWidget(ToolWidget):
    """Shows the interrupt's message with Approve / Reject. Schemas it cannot fill only get Cancel."""

    DEFAULT_CSS = """
    InterruptWidget { border: none; border-left: thick $warning; }
    InterruptWidget #buttons { height: auto; margin-top: 1; }
    InterruptWidget Button { margin-right: 1; }
    """

    def __init__(self, interrupt: Any) -> None:
        super().__init__(interrupt.id, "interrupt")
        self.interrupt = interrupt
        self.simple = asks_for_approval(interrupt.response_schema)
        self.answered = False

    def compose(self) -> ComposeResult:
        yield Static(id="body")
        with Horizontal(id="buttons"):
            if self.simple:
                yield Button("Approve", id="approve", variant="success")
                yield Button("Reject", id="reject", variant="error")
            else:
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        i = self.interrupt
        lines = [Text(f"⏸ {i.message or 'The agent is waiting for you'}", style="bold")]
        if not self.simple:
            lines.append(Text("This prompt needs input Gentui cannot provide yet.", style="dim italic"))
        self.show(Text("\n").join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if self.answered:
            return
        self.answered = True
        for button in self.query(Button):
            button.disabled = True
        if event.button.id == "approve":
            self.answer(self.interrupt.id, "resolved", {"approved": True})
        elif event.button.id == "reject":
            self.answer(self.interrupt.id, "resolved", {"approved": False})
        else:
            self.answer(self.interrupt.id, "cancelled")
