"""Base class for widgets that render a tool call ("the tool call IS the UI")."""

import json
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static


def parse_partial_json(text: str) -> dict[str, Any] | None:
    """Parse streamed tool args. None until the JSON is complete (-> show a skeleton)."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class ToolWidget(Vertical):
    """Lifecycle, driven by the TUI from TOOL_CALL_* events:

        on_start()         TOOL_CALL_START   -> show a skeleton
        on_args(args)      TOOL_CALL_ARGS    -> args parsed so far (may be called repeatedly)
        on_end(args)       TOOL_CALL_END     -> final args
        on_result(text)    TOOL_CALL_RESULT  -> what the tool returned
        on_interrupt(i)    RUN_FINISHED      -> the run is waiting for a decision on this call

    Subclasses override what they need. To talk back to the agent (button clicks, forms),
    call `self.submit(text, props)`; the app sends it as the next user message.
    """

    # Only one instance per conversation (e.g. the plan): later tool calls update it in place.
    singleton = False

    DEFAULT_CSS = """
    ToolWidget {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
        border: none; border-left: thick $primary 60%;
    }
    """

    class Submit(Message):
        """Ask the app to send `text` as the next user message (plus out-of-band `props`)."""

        def __init__(self, text: str, props: dict[str, Any] | None = None) -> None:
            super().__init__()
            self.text = text
            self.props = props or {}

    class Answer(Message):
        """Answer an open AG-UI interrupt (the app sends the `resume` run once all are answered)."""

        def __init__(self, interrupt_id: str, status: str, payload: Any = None) -> None:
            super().__init__()
            self.interrupt_id = interrupt_id
            self.status = status  # "resolved" | "cancelled"
            self.payload = payload

    def __init__(self, call_id: str, tool_name: str) -> None:
        super().__init__()
        self.call_id = call_id
        self.tool_name = tool_name
        self.args: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Static(id="body")

    def show(self, renderable: Any) -> None:
        """Replace the main body content (simple widgets only need this)."""
        self.query_one("#body", Static).update(renderable)

    def submit(self, text: str, props: dict[str, Any] | None = None) -> None:
        self.post_message(self.Submit(text, props))

    def answer(self, interrupt_id: str, status: str, payload: Any = None) -> None:
        self.post_message(self.Answer(interrupt_id, status, payload))

    def on_start(self) -> None: ...
    def on_args(self, args: dict[str, Any]) -> None:
        self.args = args

    def on_end(self, args: dict[str, Any]) -> None:
        self.args = args

    def on_result(self, text: str) -> None: ...

    def on_interrupt(self, interrupt: Any) -> bool:
        """The run ended waiting on this tool call (RUN_FINISHED outcome "interrupt"). Return True
        if this widget will answer it with `self.answer(...)`; False lets the app show a generic prompt."""
        return False
