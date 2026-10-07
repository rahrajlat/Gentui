"""Textual app: streaming chat + generative UI widgets rendered from AG-UI events."""

import asyncio
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Protocol

import httpx
import jsonpatch
from ag_ui.core import BaseEvent, EventType
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.worker import WorkerCancelled, WorkerFailed
from textual.theme import Theme
from textual.widgets import Collapsible, Input, Markdown, RichLog, Static
from textual.widgets._markdown import MarkdownStream

from gentui import plugins
from gentui.config import Config
from gentui.tui import branding, commands, widgets  # noqa: F401  (registers built-in widgets and commands)
from gentui.tui.splash import SplashScreen
from gentui.tui.transcript import Transcript
from gentui.tui.agui_client import AguiClient, BackendError
from gentui.tui.widgets.base import ToolWidget, parse_partial_json
from gentui.tui.widgets.interrupt import InterruptWidget
from gentui.tui.widgets.plan import PlanWidget
from gentui.tui.widgets.registry import widget_for

# Gentui's own look: teal and violet on near-black.
GENTUI_THEME = Theme(
    name="gentui",
    primary="#4FD6C8",
    secondary="#A78BFA",
    accent="#7DD3FC",
    foreground="#E6E9EF",
    background="#14161B",
    surface="#1D2027",
    panel="#242832",
    success="#7BD88F",
    warning="#F2C46D",
    error="#F27C86",
    dark=True,
)

# Warm coral on near-black (the earlier look), still available with `/theme claude`.
CLAUDE_THEME = Theme(
    name="claude",
    primary="#D97757",
    secondary="#B8A99A",
    accent="#E8A07F",
    foreground="#ECE9E3",
    background="#1B1A19",
    surface="#262422",
    panel="#2E2B29",
    success="#8FB573",
    warning="#E3B35C",
    error="#E5736A",
    dark=True,
)


class Client(Protocol):
    def run(self, thread_id: str, text: str, forwarded_props: dict[str, Any] | None = ..., resume: Any = ...) -> Any: ...


class GentuiApp(App[None]):
    SPLASH_IN_HEADLESS = False  # tests turn the splash off; the splash tests turn it back on
    SPLASH_SECONDS = 2.4

    CSS = """
    Screen { background: $background; }
    #chat { padding: 0 2; }
    #brand { width: auto; height: auto; margin: 1 0 0 1; }
    #welcome { border: round $primary 70%; padding: 0 2; margin: 1 0 0 0; color: $text; }
    .welcome { color: $text-muted; margin: 1 0 0 0; }
    .row { height: auto; margin: 1 0 0 0; }
    .mark { width: 2; color: $primary; text-style: bold; }
    .time { width: auto; padding: 0 0 0 2; color: $text-muted 70%; }
    .user { width: 1fr; background: $surface; padding: 0 1; }
    .assistant { width: 1fr; padding: 0; background: transparent; }
    .thinking { color: $text-muted; text-style: italic; }
    Collapsible.thought { margin: 1 0 0 0; padding: 0; border: none; background: transparent; }
    Collapsible.thought > CollapsibleTitle { color: $text-muted; padding: 0; background: transparent; }
    Collapsible.thought > Contents { padding: 0 0 0 2; }
    .error { color: $error; border: none; border-left: thick $error; padding: 0 1; margin: 1 0 0 0; }
    #busy { height: 1; margin: 0 3; color: $primary; }
    #promptbox { height: 3; border: round $primary 50%; margin: 0 1; padding: 0 1; }
    #promptbox:focus-within { border: round $primary; }
    #promptmark { width: 2; color: $primary; text-style: bold; }
    #prompt { border: none; background: transparent; padding: 0; height: 1; }
    #prompt:focus { border: none; background: transparent; }
    #statusbar { height: 1; margin: 0 3; color: $text-muted; }
    #statusbar .left { width: 1fr; }
    #statusbar .right { width: auto; }
    #dev { display: none; width: 45%; border-left: tall $primary 40%; padding: 0 1; }
    #dev.-visible { display: block; }
    #events { height: 1fr; }
    """

    BINDINGS = [
        Binding("d", "toggle_dev", "Dev pane"),
        # Textual itself binds ctrl+q to quit (as a priority binding). Gentui uses slash commands instead
        # (/quit, /dev), so that key is switched off rather than just left out of this list.
        Binding("ctrl+q", "ignore", show=False, priority=True),
    ]

    def __init__(self, client: Client, config: Config | None = None) -> None:
        self.config = config or Config()
        # a user CSS file is hot-reloaded: edit it while the app runs
        super().__init__(css_path=self.config.css, watch_css=bool(self.config.css))
        self.title = self.config.title
        self.sub_title = self.config.subtitle
        self.register_theme(GENTUI_THEME)
        self.register_theme(CLAUDE_THEME)
        self.client = client
        if hasattr(client, "on_raw"):
            client.on_raw = self._log_raw
        self.show_reasoning = self.config.show_reasoning
        self._plugin_errors = plugins.load_all(
            self.config.plugins, self.config.widgets, self.config.default_widget
        )
        self.thread_id = str(uuid.uuid4())
        self.state: dict[str, Any] = {}  # shared state mirrored from the backend
        self.transcript = Transcript()  # what /export_md writes

        self._outbox: deque[tuple[str, dict[str, Any] | None, list[dict[str, Any]] | None]] = deque()
        self._open_interrupts: dict[str, Any] = {}  # AG-UI interrupts waiting for an answer
        self._answers: dict[str, dict[str, Any]] = {}
        self._busy = False
        self._busy_since = 0.0
        self._text_streams: dict[str, MarkdownStream] = {}  # open assistant messages
        self._thoughts: dict[str, tuple[Collapsible, Static, str, float]] = {}  # open reasoning blocks
        self._tool_widgets: dict[str, ToolWidget] = {}  # tool_call_id -> widget
        self._tool_arg_buf: dict[str, str] = {}  # tool_call_id -> raw args received so far
        self._singletons: dict[type, ToolWidget] = {}

    # -- layout --------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical():
                brand = (
                    [Static(branding.logo_static(branding.wordmark_for(self.size.width or 80)), id="brand")]
                    if self.config.logo
                    else []
                )
                yield VerticalScroll(
                    *brand,
                    Static(Text(self.config.welcome_text), id="welcome"),
                    id="chat",
                )
                yield Static(id="busy")
                with Horizontal(id="promptbox"):
                    yield Static(branding.USER_MARK, id="promptmark")
                    yield Input(placeholder=self.config.placeholder, id="prompt")
                with Horizontal(id="statusbar"):
                    yield Static("/help · /new · /export_md · /dev · /quit", classes="left")
                    yield Static(self.config.target, classes="right")
            with Vertical(id="dev"):
                yield RichLog(id="events", wrap=True, markup=False, highlight=False)

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
        self.set_interval(0.08, self._tick)  # fast enough for the spinner and shimmer
        self.query_one("#chat", VerticalScroll).anchor()  # stay scrolled to the newest content
        self.query_one("#prompt", Input).focus()
        if self.config.splash and (not self.is_headless or self.SPLASH_IN_HEADLESS):
            self.push_screen(SplashScreen(self.SPLASH_SECONDS), lambda _: self.query_one("#prompt", Input).focus())

    def action_ignore(self) -> None:
        """Does nothing: used to switch off a key Textual binds by default."""

    def action_help_quit(self) -> None:
        """Textual's ctrl+c hint says "press ctrl+q to quit"; here the way out is /quit."""
        self.notify("Type /quit to exit", title="Quit")

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
        self.transcript.user(text)
        await self._mount(self._row(f"{branding.USER_MARK} ", Static(Text(text), classes="user"), mark_class="user-mark"))
        self.send(text)

    @on(ToolWidget.Submit)
    def _on_widget_submit(self, event: ToolWidget.Submit) -> None:
        """A widget (button, form...) wants to tell the agent something."""
        self.send(event.text, event.props)

    @on(ToolWidget.Answer)
    def _on_widget_answer(self, event: ToolWidget.Answer) -> None:
        """A widget answered an interrupt; resume once every open interrupt has an answer."""
        if event.interrupt_id not in self._open_interrupts:
            return
        self._record_decision(event)
        entry: dict[str, Any] = {"interruptId": event.interrupt_id, "status": event.status}
        if event.payload is not None:
            entry["payload"] = event.payload
        self._answers[event.interrupt_id] = entry
        if set(self._answers) >= set(self._open_interrupts):  # the spec: answer ALL open interrupts
            entries = [self._answers[i] for i in self._open_interrupts]
            self._open_interrupts, self._answers = {}, {}
            self.send("", resume=entries)

    def send(
        self, text: str, props: dict[str, Any] | None = None, resume: list[dict[str, Any]] | None = None
    ) -> None:
        self._outbox.append((text, props, resume))
        if not self._busy:  # one run at a time; extra messages wait their turn
            self._busy = True
            self.run_worker(self._drain(), group="agent")

    async def _drain(self) -> None:
        try:
            while self._outbox:
                text, props, resume = self._outbox.popleft()
                if self.config.forwarded_props:
                    props = {**self.config.forwarded_props, **(props or {})}
                self._busy_since = time.monotonic()
                self.sub_title = "thinking…"
                try:
                    stream = (
                        self.client.run(self.thread_id, text, props, resume)
                        if resume
                        else self.client.run(self.thread_id, text, props)
                    )
                    async for event in stream:
                        await self._handle(event)
                except httpx.HTTPError as exc:
                    await self._error(f"Cannot talk to the backend: {exc!r}. Is it running?")
                except BackendError as exc:
                    await self._error(str(exc))
        finally:
            self._busy = False
            self.sub_title = self.config.subtitle

    # -- AG-UI event -> UI --------------------------------------------------------------------

    async def _handle(self, ev: BaseEvent) -> None:
        self._log_event(ev)
        t = ev.type
        if t == EventType.TEXT_MESSAGE_START:
            message = Markdown(classes="assistant")
            await self._mount(self._row(branding.MARK, message))
            self._text_streams[ev.message_id] = Markdown.get_stream(message)
            self.transcript.open_text(ev.message_id)
        elif t == EventType.TEXT_MESSAGE_CONTENT:
            self.transcript.append_text(ev.message_id, ev.delta)
            await self._text_streams[ev.message_id].write(ev.delta)
        elif t == EventType.TEXT_MESSAGE_END:
            await self._text_streams.pop(ev.message_id).stop()
        elif t == EventType.REASONING_MESSAGE_START and self.show_reasoning:
            body = Static(classes="thinking")
            box = Collapsible(body, title=f"{branding.MARK} Thinking…", collapsed=False, classes="thought")
            await self._mount(box)
            self._thoughts[ev.message_id] = (box, body, "", time.monotonic())
        elif t == EventType.REASONING_MESSAGE_CONTENT:
            if ev.message_id in self._thoughts:
                box, body, text, t0 = self._thoughts[ev.message_id]
                text += ev.delta
                self._thoughts[ev.message_id] = (box, body, text, t0)
                body.update(Text(text))
        elif t == EventType.REASONING_MESSAGE_END:
            if ev.message_id in self._thoughts:
                box, _, thought, t0 = self._thoughts.pop(ev.message_id)
                seconds = max(1, round(time.monotonic() - t0))
                self.transcript.reasoning(thought, seconds)
                box.title = f"{branding.MARK} Thought for {seconds}s"
                box.collapsed = True  # tuck it away once the answer starts
        elif t == EventType.TOOL_CALL_START:
            self.transcript.tool_start(ev.tool_call_id, ev.tool_call_name)
            await self._tool_start(ev.tool_call_id, ev.tool_call_name)
        elif t == EventType.TOOL_CALL_ARGS:
            self.transcript.tool_args(ev.tool_call_id, ev.delta)
            self._tool_arg_buf[ev.tool_call_id] = self._tool_arg_buf.get(ev.tool_call_id, "") + ev.delta
            args = parse_partial_json(self._tool_arg_buf[ev.tool_call_id])
            if args is not None and (w := self._tool_widgets.get(ev.tool_call_id)):
                w.on_args(args)
        elif t == EventType.TOOL_CALL_END:
            args = parse_partial_json(self._tool_arg_buf.get(ev.tool_call_id, "")) or {}
            if w := self._tool_widgets.get(ev.tool_call_id):
                w.on_end(args)
        elif t == EventType.TOOL_CALL_RESULT:
            self.transcript.tool_result(ev.tool_call_id, ev.content)
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
        elif t == EventType.RUN_FINISHED:
            outcome = getattr(ev, "outcome", None)
            if outcome is not None and outcome.type == "interrupt":
                await self._on_interrupts(outcome.interrupts)
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

    async def _on_interrupts(self, interrupts: list[Any]) -> None:
        """The run ended waiting for decisions. A widget bound to the interrupt's tool call answers
        it; anything unclaimed gets a generic Approve / Reject prompt."""
        self._open_interrupts = {i.id: i for i in interrupts}
        self._answers = {}
        for interrupt in interrupts:
            widget = self._tool_widgets.get(interrupt.tool_call_id or "")
            if widget is None or not widget.on_interrupt(interrupt):
                await self._mount(InterruptWidget(interrupt))

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

    def _row(self, mark: str, body: Any, mark_class: str = "bullet") -> Horizontal:
        """One chat line: a marker (`>` you, `●` agent), the content, and the time it was sent."""
        children: list[Any] = [Static(mark, classes=f"mark {mark_class}"), body]
        if self.config.show_time:
            children.append(Static(datetime.now().strftime(self.config.time_format), classes="time"))
        return Horizontal(*children, classes="row")

    def _tick(self) -> None:
        """Animate the 'working' line above the prompt while a run is in flight."""
        try:  # the main screen, even while the splash is on top; it may not be built yet at startup
            busy = self.screen_stack[0].query_one("#busy", Static)
        except NoMatches:
            return
        if not self._busy:
            busy.update("")
            return
        busy.update(branding.thinking_label(time.monotonic() - self._busy_since))

    async def mount_chat(self, widget: Any) -> None:
        """Public: add any widget to the conversation (for plugins and widgets)."""
        await self.query_one("#chat", VerticalScroll).mount(widget)

    _mount = mount_chat

    def _record_decision(self, event: ToolWidget.Answer) -> None:
        """Note your Approve / Reject / Cancel click in the transcript."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.status == "cancelled":
            self.transcript.decision("Rejected")
        elif payload.get("approved") is True:
            edited = payload.get("command")
            self.transcript.decision(f"Approved (edited to `{edited}`)" if edited else "Approved")
        elif payload.get("approved") is False:
            self.transcript.decision("Rejected")
        else:
            self.transcript.decision("Answered")

    async def _stop_run(self) -> None:
        """Cancel the agent run in flight (if any) and drop messages waiting to be sent."""
        self._outbox.clear()
        for worker in self.workers.cancel_group(self, "agent"):
            try:
                await worker.wait()
            except (WorkerCancelled, WorkerFailed, asyncio.CancelledError):
                pass  # it was cancelled on purpose
        self._busy = False

    async def new_thread(self) -> None:
        """Clear the screen and start a fresh conversation (new thread id, empty state).

        A run still in flight is stopped first, so the old answer cannot stream into the new chat."""
        await self._stop_run()
        self.transcript.clear()
        self._text_streams.clear()
        self.thread_id = str(uuid.uuid4())
        self.state = {}
        self._tool_widgets.clear()
        self._tool_arg_buf.clear()
        self._singletons.clear()
        self._thoughts.clear()
        self._open_interrupts, self._answers = {}, {}
        for child in list(self.query_one("#chat", VerticalScroll).children):
            if child.id not in ("brand", "welcome"):
                await child.remove()

    async def _error(self, message: str) -> None:
        self.transcript.error(message)
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
