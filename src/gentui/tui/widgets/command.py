"""Command widget: shows a proposed shell command with Approve / Edit / Reject."""

import platform
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static

from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

RISK_COLOR = {"safe": "green", "caution": "yellow", "dangerous": "red"}
LEXER = "powershell" if platform.system() == "Windows" else "bash"


@register_widget("propose_command")
class CommandWidget(ToolWidget):
    DEFAULT_CSS = """
    CommandWidget { border: none; border-left: thick $accent; }
    CommandWidget #editor { display: none; margin-top: 1; }
    CommandWidget #buttons { height: auto; margin-top: 1; }
    CommandWidget Button { margin-right: 1; }
    CommandWidget #status { margin-top: 1; display: none; }
    """

    # waiting (args streaming) -> ready (buttons live) -> approved | rejected | blocked
    state = "waiting"
    editing = False
    interrupt: Any = None  # the AG-UI interrupt waiting on this proposal, once the run finishes

    def compose(self) -> ComposeResult:
        yield Static(id="body")
        yield Input(id="editor")
        with Horizontal(id="buttons"):
            yield Button("Approve", id="approve", variant="success", disabled=True)
            yield Button("Edit", id="edit", disabled=True)
            yield Button("Reject", id="reject", variant="error", disabled=True)
        yield Static(id="status")

    # -- tool call lifecycle -----------------------------------------------------------

    def on_start(self) -> None:
        self._draw()  # skeleton: args from Ollama usually arrive in one piece

    def on_args(self, args: dict[str, Any]) -> None:
        super().on_args(args)
        self._draw()

    def on_end(self, args: dict[str, Any]) -> None:
        super().on_end(args)
        self._draw()
        if self.args.get("command") and self.state == "waiting":
            self.state = "ready"
            self._set_buttons(disabled=False)

    def on_interrupt(self, interrupt: Any) -> bool:
        self.interrupt = interrupt  # decisions now go back as an AG-UI `resume`
        return True

    def on_result(self, text: str) -> None:
        if text.startswith("BLOCKED"):  # the backend's safety policy refused the proposal
            self._finish("blocked", Text(f"⊘ {text}", style="bold red"))
        elif text.startswith("Error"):  # the tool call itself failed; the agent usually retries
            self._finish("failed", Text("! This proposal failed; the agent will try again.", style="yellow"))

    # -- drawing ---------------------------------------------------------------------------

    def _draw(self) -> None:
        command = self.args.get("command")
        if not command:
            self.show(Text("$ Proposing a command…", style="dim italic"))
            return
        risk = str(self.args.get("risk", "caution"))
        badge = Text(f" {risk.upper()} ", style=f"bold black on {RISK_COLOR.get(risk, 'yellow')}")
        header = Text.assemble(("$ Proposed command  ", "bold"), badge)
        body = Syntax(command, LEXER, theme="ansi_dark", word_wrap=True, background_color="default")
        explanation = Text(str(self.args.get("explanation", "")), style="italic")
        self.show(Group(header, body, explanation))

    def _set_buttons(self, disabled: bool) -> None:
        for button in self.query(Button):
            button.disabled = disabled or self.app.READ_ONLY

    def _finish(self, state: str, status: Text) -> None:
        self.state = state
        self._set_buttons(disabled=True)
        self.query_one("#editor", Input).display = False
        status_line = self.query_one("#status", Static)
        status_line.update(status)
        status_line.display = True

    # -- user decisions ------------------------------------------------------------------

    def replay_decision(self, status: str, payload: Any = None) -> None:
        if self.state != "ready":
            return
        payload = payload if isinstance(payload, dict) else {}
        if status == "cancelled" or payload.get("approved") is False:
            self._finish("rejected", Text("✖ Rejected", style="red"))
        elif payload.get("command"):
            self._finish("approved", Text(f"✔ Approved (edited to {payload['command']}) — running…", style="green"))
        else:
            self._finish("approved", Text("✔ Approved — running…", style="green"))

    def _approve(self) -> None:
        editor = self.query_one("#editor", Input)
        command = (editor.value if self.editing else self.args.get("command", "")).strip()
        if not command:
            return
        self._finish("approved", Text("✔ Approved — running…", style="green"))
        if self.interrupt is not None:  # AG-UI interrupt: the backend remembers the proposed command
            payload: dict[str, Any] = {"approved": True}
            if command != str(self.args.get("command", "")).strip():
                payload["command"] = command  # only an edit travels back
            self.answer(self.interrupt.id, "resolved", payload)
            return
        self.submit(
            f"Approved (approval_id={self.call_id}). Call run_command with this approval_id.",
            {"approval": {"decision": "approve", "command": command, "toolCallId": self.call_id}},
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if self.state != "ready" or self.app.READ_ONLY:
            return
        if event.button.id == "approve":
            self._approve()
        elif event.button.id == "reject":
            self._finish("rejected", Text("✖ Rejected", style="red"))
            if self.interrupt is not None:
                self.answer(self.interrupt.id, "cancelled")
                return
            self.submit(
                "Rejected. Do not run it.",
                {"approval": {"decision": "reject", "toolCallId": self.call_id}},
            )
        elif event.button.id == "edit":
            self.editing = not self.editing
            editor = self.query_one("#editor", Input)
            editor.display = self.editing
            event.button.label = "Cancel edit" if self.editing else "Edit"
            self.query_one("#approve", Button).label = "Approve edit" if self.editing else "Approve"
            if self.editing:
                editor.value = self.args.get("command", "")
                editor.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()  # Enter in the editor = approve the edited command
        if self.state == "ready":
            self._approve()
