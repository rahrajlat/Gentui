"""`gentui --replay NAME`: play a recorded session back, with pause / play, a scrubber and a speed control.

The recording is the user's messages plus the AG-UI events the backend streamed, so the replay feeds them to the
same code that draws a live chat: every widget (tools, charts, plan, approvals) and the collapsible chain of thought
look and work as they did. Seeking backwards clears the chat and re-applies the events up to that moment.
"""

import asyncio
import time
from datetime import timedelta
from typing import Any

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Collapsible, RichLog, Static

from gentui.config import Config
from gentui.session import Item, Session
from gentui.tui.app import GentuiApp
from gentui.tui.widgets.interrupt import InterruptWidget

SPEEDS = (0.5, 1.0, 2.0, 4.0, 8.0)
STEP = 5.0  # seconds the arrow keys jump


def clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


class Scrubber(Widget, can_focus=False):
    """A one-line slider: click or drag to seek. Diamonds mark where you sent a message."""

    DEFAULT_CSS = "Scrubber { height: 1; width: 1fr; }"

    position = reactive(0.0)  # 0..1

    class Seek(Message):
        def __init__(self, fraction: float) -> None:
            super().__init__()
            self.fraction = fraction

    def __init__(self, marks: list[float], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.marks = marks
        self._dragging = False

    def render(self) -> Text:
        width = max(self.size.width, 2)
        handle = round(self.position * (width - 1))
        marks = {round(m * (width - 1)) for m in self.marks}
        line = Text(no_wrap=True)
        for i in range(width):
            if i == handle:
                line.append("●", style="bold " + self.app.theme_variables.get("primary", "cyan"))
            elif i in marks:
                line.append("◆", style=self.app.theme_variables.get("accent", "cyan"))
            elif i < handle:
                line.append("━", style=self.app.theme_variables.get("primary", "cyan"))
            else:
                line.append("─", style="dim")
        return line

    def _seek_to(self, x: float) -> None:
        self.post_message(self.Seek(min(max(x / max(self.size.width - 1, 1), 0.0), 1.0)))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.capture_mouse()
        self._seek_to(event.x)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging:
            self._seek_to(event.x)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._dragging = False
        self.release_mouse()


class PlainButton(Button, can_focus=False):
    """A button that never takes the keyboard focus, so the space bar always means play / pause."""


class ReplayBar(Horizontal):
    DEFAULT_CSS = """
    ReplayBar { height: 1; margin: 0 3; }
    ReplayBar PlainButton { width: 10; min-width: 10; }
    ReplayBar #speed { width: 6; min-width: 6; margin-left: 1; }
    ReplayBar #scrubber { margin: 0 2; }
    ReplayBar #clock { width: auto; color: $text-muted; }
    """

    def __init__(self, marks: list[float]) -> None:
        super().__init__(id="replaybar")
        self.marks = marks

    def compose(self) -> ComposeResult:
        yield PlainButton("⏸ Pause", id="playpause", compact=True)
        yield Scrubber(self.marks, id="scrubber")
        yield Static("0:00 / 0:00", id="clock")
        yield PlainButton("1×", id="speed", compact=True)


class ReplayApp(GentuiApp):
    READ_ONLY = True
    BINDINGS = [
        Binding("space", "toggle_play", "Play / pause", priority=True),
        Binding("left", "skip(-1)", "Back 5s", priority=True),
        Binding("right", "skip(1)", "Forward 5s", priority=True),
        Binding("home", "restart", "Restart", priority=True),
        Binding("plus,equals_sign", "speed(1)", "Faster", priority=True),
        Binding("minus", "speed(-1)", "Slower", priority=True),
        Binding("t", "toggle_thoughts", "Thoughts", priority=True),
        Binding("q", "quit", "Quit", priority=True),
    ]

    def __init__(self, session: Session, config: Config | None = None) -> None:
        config = config or Config()
        config.splash = False
        config.url = f"replay: {session.path.name}"
        config.welcome = (
            f"◈ Replaying {session.path.name}"
            + (f", recorded {session.recorded_at:%Y-%m-%d %H:%M}" if session.items else ", an empty recording")
            + "\n\n  space play/pause · ←/→ jump 5s · drag the bar to seek · +/- speed\n"
            "  t opens or closes every chain of thought (or click one) · d event inspector · q quit"
        )
        super().__init__(object(), config)  # no client: nothing is ever sent
        self.session = session
        self.playing = True
        self.speed = 1.0
        self.pos = 0.0  # seconds on the replay timeline
        self._index = 0  # items before this one are on screen
        self._seek: float | None = None
        self._item_t = 0.0

    def compose_bottom(self) -> ComposeResult:
        duration = self.session.duration or 1.0
        yield ReplayBar([i.v / duration for i in self.session.items if i.kind == "user"])
        with Horizontal(id="statusbar"):
            yield Static("space play/pause · ←/→ ±5s · +/- speed · t thoughts · d events · q quit", classes="left")
            yield Static(self.config.target, classes="right")

    def on_ready(self, event: events.Ready) -> None:
        self.run_worker(self._playback(), group="replay")
        self._refresh_bar()

    # -- the clocks the app asks for ---------------------------------------------------------

    def _now(self) -> float:
        return self._item_t

    def _wall(self):
        return self.session.recorded_at + timedelta(seconds=self._item_t)

    # -- playback -----------------------------------------------------------------------------

    async def _playback(self) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.05)
            now = time.monotonic()
            dt, last = now - last, now
            try:
                if self._seek is not None:
                    target, self._seek = self._seek, None
                    await self._jump(target)
                elif self.playing:
                    self.pos = min(self.pos + dt * self.speed, self.session.duration)
                    await self._advance()
                    if self._index >= len(self.session.items) and self.pos >= self.session.duration:
                        self.playing = False
            except NoMatches:  # the screen is going away (quitting): stop quietly
                return
            self._refresh_bar()

    async def _advance(self) -> None:
        items = self.session.items
        while self._index < len(items) and items[self._index].v <= self.pos + 1e-9:
            await self._apply(items[self._index])
            self._index += 1

    async def _jump(self, target: float) -> None:
        target = min(max(target, 0.0), self.session.duration)
        if target < self.pos or (self._index and target == 0.0):  # backwards: start over and catch up
            await self._reset()
            self._index = 0
        self.pos = target
        await self._advance()

    async def _reset(self) -> None:
        await self.new_thread()
        self.query_one("#events", RichLog).clear()
        self._item_t = 0.0

    async def _apply(self, item: Item) -> None:
        self._item_t = item.t
        if item.kind == "user":
            await self.show_user_message(item.data.get("text", ""))
        elif item.kind == "event" and item.event is not None:
            await self._handle(item.event)
        elif item.kind == "resume":
            for entry in item.data.get("entries") or []:
                self._show_decision(entry.get("interruptId", ""), entry.get("status", ""), entry.get("payload"))
            self._open_interrupts, self._answers = {}, {}
        elif item.kind == "submit":  # an older backend: the card's click was sent as a message
            approval = (item.data.get("props") or {}).get("approval") or {}
            widget = self._tool_widgets.get(approval.get("toolCallId", ""))
            if widget is not None:
                approved = approval.get("decision") == "approve"
                payload: dict[str, Any] = {"approved": approved}
                if approval.get("command"):
                    payload["command"] = approval["command"]
                widget.replay_decision("resolved" if approved else "cancelled", payload)
        elif item.kind == "new":
            await self._reset()
            self._item_t = item.t

    def _show_decision(self, interrupt_id: str, status: str, payload: Any) -> None:
        interrupt = self._open_interrupts.get(interrupt_id)
        widget = self._tool_widgets.get(getattr(interrupt, "tool_call_id", None) or "")
        if widget is None:
            widget = next((w for w in self.query(InterruptWidget) if w.interrupt.id == interrupt_id), None)
        if widget is not None:
            widget.replay_decision(status, payload)

    # -- controls -------------------------------------------------------------------------------

    def _refresh_bar(self) -> None:
        duration = self.session.duration
        try:
            scrubber = self.query_one("#scrubber", Scrubber)
        except NoMatches:  # the app is starting or shutting down
            return
        scrubber.position = self.pos / duration if duration else 1.0
        self.query_one("#clock", Static).update(f"{clock(self.pos)} / {clock(duration)}")
        finished = not self.playing and self._index >= len(self.session.items)
        self.query_one("#playpause", Button).label = "↻ Replay" if finished else "⏸ Pause" if self.playing else "▶ Play"
        self.query_one("#speed", Button).label = f"{self.speed:g}×"

    def seek(self, seconds: float) -> None:
        self._seek = seconds

    def action_toggle_play(self) -> None:
        if self._index >= len(self.session.items):
            self.seek(0.0)  # at the end: play again from the start
            self.playing = True
        else:
            self.playing = not self.playing
        self._refresh_bar()

    def action_skip(self, direction: int) -> None:
        self.seek((self._seek if self._seek is not None else self.pos) + direction * STEP)

    def action_restart(self) -> None:
        self.seek(0.0)

    def action_speed(self, direction: int) -> None:
        at = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - self.speed))
        self.speed = SPEEDS[min(max(at + direction, 0), len(SPEEDS) - 1)]
        self._refresh_bar()

    def action_toggle_thoughts(self) -> None:
        boxes = list(self.query(Collapsible).filter(".thought"))
        any_open = any(not box.collapsed for box in boxes)
        for box in boxes:
            box.collapsed = any_open

    async def action_quit(self) -> None:
        self.exit()

    @on(Button.Pressed, "#playpause")
    def _on_playpause(self) -> None:
        self.action_toggle_play()

    @on(Button.Pressed, "#speed")
    def _on_speed(self) -> None:
        self.speed = SPEEDS[(SPEEDS.index(self.speed) + 1) % len(SPEEDS)] if self.speed in SPEEDS else 1.0
        self._refresh_bar()

    @on(Scrubber.Seek)
    def _on_scrub(self, event: Scrubber.Seek) -> None:
        self.seek(event.fraction * self.session.duration)
