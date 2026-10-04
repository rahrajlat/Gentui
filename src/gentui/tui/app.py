"""Textual app: streaming chat + generative UI widgets rendered from AG-UI events."""

import argparse
import uuid
from collections import deque
from typing import Any, Protocol

import httpx
import jsonpatch
from ag_ui.core import BaseEvent, EventType
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Collapsible, Footer, Header, Input, Markdown, RichLog, Static
from textual.widgets._markdown import MarkdownStream

from gentui import plugins
from gentui.config import Config
from gentui.tui import commands, widgets  # noqa: F401  (registers built-in widgets and commands)
from gentui.tui.agui_client import AguiClient
from gentui.tui.widgets.base import ToolWidget, parse_partial_json
from gentui.tui.widgets.plan import PlanWidget
from gentui.tui.widgets.registry import widget_for


class Client(Protocol):
    def run(self, thread_id: str, text: str, forwarded_props: dict[str, Any] | None = ...) -> Any: ...


class GentuiApp(App[None]):
    CSS = """
    #chat { padding: 0 2; }
    #prompt { margin: 0 1; }
    .user { background: $primary 25%; padding: 0 1; margin: 1 0 0 10; }
    .assistant { padding: 0 1; margin: 1 4 0 0; background: transparent; }
    .thinking { color: $text-muted; text-style: italic; }
    Collapsible.thought { margin: 1 4 0 0; padding: 0; border: none; background: transparent; }
    .error { color: $error; border: round $error; padding: 0 1; margin: 1 0; }
    #welcome, .welcome { color: $text-muted; margin: 1 0; }
    #dev { display: none; width: 45%; border-left: tall $primary 40%; padding: 0 1; }
    #dev.-visible { display: block; }
    #events { height: 1fr; }
    """

    BINDINGS = [
        Binding("d", "toggle_dev", "Dev pane"),
        Binding("ctrl+d", "toggle_dev", "Dev pane", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, client: Client, config: Config | None = None) -> None:
        self.config = config or Config()
        # a user CSS file is hot-reloaded: edit it while the app runs
        super().__init__(css_path=self.config.css, watch_css=bool(self.config.css))
        self.title = self.config.title
        self.sub_title = self.config.subtitle
        self.client = client
        if hasattr(client, "on_raw"):
            client.on_raw = self._log_raw
        self.show_reasoning = self.config.show_reasoning
        self._plugin_errors = plugins.load_all(
            self.config.plugins, self.config.widgets, self.config.default_widget
        )
        self.thread_id = str(uuid.uuid4())
        self.state: dict[str, Any] = {}  # shared state mirrored from the backend

        self._outbox: deque[tuple[str, dict[str, Any] | None]] = deque()
        self._busy = False
        self._text_streams: dict[str, MarkdownStream] = {}  # open assistant messages
        self._thoughts: dict[str, tuple[Collapsible, Static, str]] = {}  # open reasoning blocks
        self._tool_widgets: dict[str, ToolWidget] = {}  # tool_call_id -> widget
        self._tool_arg_buf: dict[str, str] = {}  # tool_call_id -> raw args received so far
        self._singletons: dict[type, ToolWidget] = {}

    # -- layout --------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical():
                yield VerticalScroll(
                    Static(Text(self.config.welcome_text), id="welcome"),
                    id="chat",
                )
                yield Input(placeholder=self.config.placeholder, id="prompt")
            with Vertical(id="dev"):
                yield RichLog(id="events", wrap=True, markup=False, highlight=False)
        yield Footer()

    async def on_mount(self) -> None:
        if self.config.theme in self.available_themes:
            self.theme = self.config.theme
        else:
            self.notify(f"unknown theme {self.config.theme!r}", severity="warning")
        if self.config.dev_pane:
            self.query_one("#dev").add_class("-visible")
        for message in self._plugin_errors:
            self.notify(message, severity="error", timeout=15)
        for setup in plugins.SETUPS:
            try:
                await plugins.call(setup, self)
            except Exception as exc:  # noqa: BLE001
                self.notify(f"plugin setup failed: {exc!r}", severity="error")
        self.query_one("#chat", VerticalScroll).anchor()  # stay scrolled to the newest content
        self.query_one("#prompt", Input).focus()

    def action_toggle_dev(self) -> None:
        self.query_one("#dev").toggle_class("-visible")

    # -- sending ---------------------------------------------------------------------------

    @on(Input.Submitted, "#prompt")
    async def _on_prompt(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        if text.startswith("/"):
            name, _, args = text[1:].partition(" ")
            if name in plugins.COMMANDS:
                await plugins.call(plugins.COMMANDS[name][0], self, args)
                return
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
                if self.config.forwarded_props:
                    props = {**self.config.forwarded_props, **(props or {})}
                self.sub_title = "thinking…"
                try:
                    async for event in self.client.run(self.thread_id, text, props):
                        await self._handle(event)
                except httpx.HTTPError as exc:
                    await self._error(f"Cannot talk to the backend: {exc!r}. Is it running?")
        finally:
            self._busy = False
            self.sub_title = self.config.subtitle

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
        elif t == EventType.REASONING_MESSAGE_START and self.show_reasoning:
            body = Static(classes="thinking")
            box = Collapsible(body, title="Thinking…", collapsed=False, classes="thought")
            await self._mount(box)
            self._thoughts[ev.message_id] = (box, body, "")
        elif t == EventType.REASONING_MESSAGE_CONTENT:
            if ev.message_id in self._thoughts:
                box, body, text = self._thoughts[ev.message_id]
                text += ev.delta
                self._thoughts[ev.message_id] = (box, body, text)
                body.update(Text(text))
        elif t == EventType.REASONING_MESSAGE_END:
            if ev.message_id in self._thoughts:
                box, _, _ = self._thoughts.pop(ev.message_id)
                box.title = "Thought"
                box.collapsed = True  # tuck it away once the answer starts
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
        await plugins.dispatch_event(self, ev)

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
        plan = self.state.get("plan") or []
        widget = self._singletons.get(PlanWidget)
        if plan and widget is None:  # a plan appeared without a todo_write widget: show one
            widget = PlanWidget("state", "todo_write")
            await self._mount(widget)
            self._singletons[PlanWidget] = widget
        if isinstance(widget, PlanWidget) and plan:
            widget.set_plan(plan)

    # -- helpers -----------------------------------------------------------------------------

    async def mount_chat(self, widget: Any) -> None:
        """Public: add any widget to the conversation (for plugins and widgets)."""
        await self.query_one("#chat", VerticalScroll).mount(widget)

    _mount = mount_chat

    async def new_thread(self) -> None:
        """Clear the screen and start a fresh conversation (new thread id, empty state)."""
        self.thread_id = str(uuid.uuid4())
        self.state = {}
        self._tool_widgets.clear()
        self._tool_arg_buf.clear()
        self._singletons.clear()
        self._thoughts.clear()
        for child in list(self.query_one("#chat", VerticalScroll).children):
            if child.id != "welcome":
                await child.remove()

    async def _error(self, message: str) -> None:
        await self._mount(Static(Text(f"✖ {message}"), classes="error"))

    def _log_raw(self, payload: str) -> None:
        """Dev pane: the backend's SSE payloads exactly as received."""
        self.query_one("#events", RichLog).write(Text(payload))

    def _log_event(self, ev: BaseEvent) -> None:
        # fallback for clients that cannot expose the raw stream
        if not hasattr(self.client, "on_raw"):
            self._log_raw(ev.model_dump_json(by_alias=True, exclude_none=True))


def main() -> None:
    from gentui.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
