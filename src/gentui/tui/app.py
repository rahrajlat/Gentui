"""Textual app: streaming chat + generative UI widgets rendered from AG-UI events."""

import argparse
import json
import uuid
from collections import deque
from typing import Any, Protocol

import httpx
import jsonpatch
from ag_ui.core import BaseEvent, EventType
from rich.json import JSON
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, Markdown, RichLog, Static
from textual.widgets._markdown import MarkdownStream

from gentui.tui import widgets  # noqa: F401  (registers the built-in widgets)
from gentui.tui.agui_client import AguiClient
from gentui.tui.widgets.base import ToolWidget, parse_partial_json
from gentui.tui.widgets.plan import PlanWidget
from gentui.tui.widgets.registry import widget_for

EVENT_COLOR = {
    "RUN": "magenta", "TEXT": "cyan", "TOOL": "yellow", "STATE": "green",
}


class Client(Protocol):
    def run(self, thread_id: str, text: str, forwarded_props: dict[str, Any] | None = ...) -> Any: ...


class GentuiApp(App[None]):
    TITLE = "Gentui"
    SUB_TITLE = "Generative UI for your terminal"

    CSS = """
    #chat { padding: 0 2; }
    #prompt { margin: 0 1; }
    .user { background: $primary 25%; padding: 0 1; margin: 1 0 0 10; }
    .assistant { padding: 0 1; margin: 1 4 0 0; background: transparent; }
    .error { color: $error; border: round $error; padding: 0 1; margin: 1 0; }
    #welcome { color: $text-muted; margin: 1 0; }
    #dev { display: none; width: 45%; border-left: tall $primary 40%; padding: 0 1; }
    #dev.-visible { display: block; }
    #events { height: 1fr; }
    #state { height: auto; max-height: 40%; border-top: solid $primary 40%; }
    """

    BINDINGS = [
        Binding("d", "toggle_dev", "Dev pane"),
        Binding("ctrl+d", "toggle_dev", "Dev pane", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, client: Client) -> None:
        super().__init__()
        self.client = client
        self.thread_id = str(uuid.uuid4())
        self.state: dict[str, Any] = {}  # shared state mirrored from the backend

        self._outbox: deque[tuple[str, dict[str, Any] | None]] = deque()
        self._busy = False
        self._text_streams: dict[str, MarkdownStream] = {}  # open assistant messages
        self._tool_widgets: dict[str, ToolWidget] = {}  # tool_call_id -> widget
        self._tool_arg_buf: dict[str, str] = {}  # tool_call_id -> raw args received so far
        self._singletons: dict[type, ToolWidget] = {}

    # -- layout --------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical():
                yield VerticalScroll(
                    Static(
                        "Ask for something to do in your shell, e.g.\n"
                        "  “what are the 5 biggest files here?”\n"
                        "Nothing runs until you approve it.   [d] dev pane",
                        id="welcome",
                    ),
                    id="chat",
                )
                yield Input(placeholder="Ask anything…", id="prompt")
            with Vertical(id="dev"):
                yield RichLog(id="events", wrap=True, markup=False, highlight=False)
                yield Static(id="state")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "tokyo-night"
        self.query_one("#chat", VerticalScroll).anchor()  # stay scrolled to the newest content
        self.query_one("#prompt", Input).focus()
        self._draw_state()

    def action_toggle_dev(self) -> None:
        self.query_one("#dev").toggle_class("-visible")

    # -- sending ---------------------------------------------------------------------------

    @on(Input.Submitted, "#prompt")
    async def _on_prompt(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        await self._mount(Static(Text(text), classes="user"))
        self.send(text)

    @on(ToolWidget.Submit)
    def _on_widget_submit(self, event: ToolWidget.Submit) -> None:
        """A widget (button, form...) wants to tell the agent something."""
        self.send(event.text, event.props)

    def send(self, text: str, props: dict[str, Any] | None = None) -> None:
        self._outbox.append((text, props))
        if not self._busy:  # one run at a time; extra messages wait their turn
            self._busy = True
            self.run_worker(self._drain(), group="agent")

    async def _drain(self) -> None:
        try:
            while self._outbox:
                text, props = self._outbox.popleft()
                self.sub_title = "thinking…"
                try:
                    async for event in self.client.run(self.thread_id, text, props):
                        await self._handle(event)
                except httpx.HTTPError as exc:
                    await self._error(f"Cannot talk to the backend: {exc!r}. Is it running?")
        finally:
            self._busy = False
            self.sub_title = "Generative UI for your terminal"

    # -- AG-UI event -> UI --------------------------------------------------------------------

    async def _handle(self, ev: BaseEvent) -> None:
        self._log_event(ev)
        t = ev.type
        if t == EventType.TEXT_MESSAGE_START:
            message = Markdown(classes="assistant")
            await self._mount(message)
            self._text_streams[ev.message_id] = Markdown.get_stream(message)
        elif t == EventType.TEXT_MESSAGE_CONTENT:
            await self._text_streams[ev.message_id].write(ev.delta)
        elif t == EventType.TEXT_MESSAGE_END:
            await self._text_streams.pop(ev.message_id).stop()
        elif t == EventType.TOOL_CALL_START:
            await self._tool_start(ev.tool_call_id, ev.tool_call_name)
        elif t == EventType.TOOL_CALL_ARGS:
            self._tool_arg_buf[ev.tool_call_id] = self._tool_arg_buf.get(ev.tool_call_id, "") + ev.delta
            args = parse_partial_json(self._tool_arg_buf[ev.tool_call_id])
            if args is not None and (w := self._tool_widgets.get(ev.tool_call_id)):
                w.on_args(args)
        elif t == EventType.TOOL_CALL_END:
            args = parse_partial_json(self._tool_arg_buf.get(ev.tool_call_id, "")) or {}
            if w := self._tool_widgets.get(ev.tool_call_id):
                w.on_end(args)
        elif t == EventType.TOOL_CALL_RESULT:
            if w := self._tool_widgets.get(ev.tool_call_id):
                w.on_result(ev.content)
        elif t == EventType.STATE_SNAPSHOT:
            self.state = ev.snapshot
            await self._on_state_changed()
        elif t == EventType.STATE_DELTA:
            # ev.delta items are pydantic models; jsonpatch wants plain dicts
            ops = [op.model_dump(by_alias=True, exclude_none=True) for op in ev.delta]
            self.state = jsonpatch.apply_patch(self.state, ops)
            await self._on_state_changed()
        elif t == EventType.RUN_ERROR:
            await self._error(ev.message)

    async def _tool_start(self, call_id: str, name: str) -> None:
        widget = widget_for(call_id, name)
        existing = self._singletons.get(type(widget)) if widget.singleton else None
        if existing is not None:
            widget = existing  # e.g. the plan: update in place instead of adding another
        else:
            await self._mount(widget)
            if widget.singleton:
                self._singletons[type(widget)] = widget
        self._tool_widgets[call_id] = widget
        widget.on_start()

    async def _on_state_changed(self) -> None:
        self._draw_state()
        plan = self.state.get("plan") or []
        widget = self._singletons.get(PlanWidget)
        if plan and widget is None:  # a plan appeared without a todo_write widget: show one
            widget = PlanWidget("state", "todo_write")
            await self._mount(widget)
            self._singletons[PlanWidget] = widget
        if isinstance(widget, PlanWidget) and plan:
            widget.set_plan(plan)

    # -- helpers -----------------------------------------------------------------------------

    async def _mount(self, widget: Any) -> None:
        await self.query_one("#chat", VerticalScroll).mount(widget)

    async def _error(self, message: str) -> None:
        await self._mount(Static(Text(f"✖ {message}"), classes="error"))

    def _draw_state(self) -> None:
        self.query_one("#state", Static).update(
            JSON(json.dumps({"state": self.state, "thread": self.thread_id[:8]}))
        )

    def _log_event(self, ev: BaseEvent) -> None:
        data = ev.model_dump(by_alias=True, exclude_none=True)
        kind = data.pop("type")
        data.pop("timestamp", None)
        color = EVENT_COLOR.get(kind.split("_")[0], "red" if "ERROR" in kind else "white")
        line = Text.assemble((f"{kind:<22}", f"bold {color}"), (json.dumps(data)[:200], "dim"))
        self.query_one("#events", RichLog).write(line)


def main() -> None:
    parser = argparse.ArgumentParser(prog="tui", description="Gentui terminal client")
    parser.add_argument("--url", default="http://localhost:8000/agent", help="AG-UI agent endpoint")
    GentuiApp(AguiClient(parser.parse_args().url)).run()


if __name__ == "__main__":
    main()
