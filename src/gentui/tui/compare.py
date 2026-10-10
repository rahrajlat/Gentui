"""`gentui --compare a,b,c`: recorded sessions side by side, as a diff.

Pick which session sits in each box from the drop-downs. The two are lined up block by block (your prompt, each
answer, each tool call) and drawn in full: streamed Markdown, tool widgets, tables, charts, the plan. What differs is
marked: green cells exist only on the right, red only on the left, yellow are in both but changed. Changed text can be
shown word by word (the default) or as it was rendered (`m`).
"""

import json
import re
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Any

from ag_ui.core import EventType
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Select, Static
from textual.widgets._markdown import MarkdownStream

from gentui.config import Config
from gentui.session import Item, Session
from gentui.tui import branding
from gentui.tui.app import GentuiApp
from gentui.tui.transcript import Transcript
from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.interrupt import InterruptWidget

# -- what is compared ------------------------------------------------------------------------


@dataclass(eq=False)
class Block:
    """One thing that was said or done: your prompt, an answer, some reasoning, or a tool call."""

    kind: str  # user | text | reasoning | tool
    text: str = ""
    name: str = ""  # tool name
    args: str = ""
    result: str | None = None

    @property
    def group(self) -> str:
        """What a changed block can be paired with: a tool call only with a call to the same tool."""
        return f"tool:{self.name}" if self.kind == "tool" else self.kind

    @property
    def sig(self) -> tuple[str, ...]:
        """Equal signatures are the same block. Reasoning always matches: it is never identical, and noise."""
        if self.kind == "tool":
            return ("tool", self.name, _canonical(self.args), self.result or "")
        if self.kind == "reasoning":
            return ("reasoning",)
        return (self.kind, self.text.strip())


def _canonical(args: str) -> str:
    try:
        return json.dumps(json.loads(args), sort_keys=True)
    except json.JSONDecodeError:
        return args.strip()


def blocks_of(session: Session, show_reasoning: bool = True) -> tuple[list[Block], dict[int, Block]]:
    """The session as ordered blocks, and which block each item (by index) belongs to."""
    blocks: list[Block] = []
    owner: dict[int, Block] = {}
    open_text: dict[str, Block] = {}
    open_tools: dict[str, Block] = {}
    open_thoughts: dict[str, Block] = {}

    def start(kind: str, ids: dict[str, Block], key: str, **data: Any) -> Block:
        block = ids[key] = Block(kind, **data)
        blocks.append(block)
        return block

    for n, item in enumerate(session.items):
        ev = item.event
        if item.kind == "user":
            owner[n] = start("user", {}, "", text=item.data.get("text", ""))
        elif ev is None:
            continue
        elif ev.type == EventType.TEXT_MESSAGE_START:
            owner[n] = start("text", open_text, ev.message_id)
        elif ev.type == EventType.TEXT_MESSAGE_CONTENT:
            if ev.message_id not in open_text:  # content without a start event: still keep it
                start("text", open_text, ev.message_id)
            owner[n] = open_text[ev.message_id]
            owner[n].text += ev.delta
        elif ev.type == EventType.TEXT_MESSAGE_END and ev.message_id in open_text:
            owner[n] = open_text[ev.message_id]
        elif ev.type == EventType.REASONING_MESSAGE_START and show_reasoning:
            owner[n] = start("reasoning", open_thoughts, ev.message_id)
        elif ev.type in (EventType.REASONING_MESSAGE_CONTENT, EventType.REASONING_MESSAGE_END):
            if block := open_thoughts.get(ev.message_id):
                owner[n] = block
                block.text += getattr(ev, "delta", "")
        elif ev.type == EventType.TOOL_CALL_START:
            owner[n] = start("tool", open_tools, ev.tool_call_id, name=ev.tool_call_name)
        elif ev.type in (EventType.TOOL_CALL_ARGS, EventType.TOOL_CALL_END, EventType.TOOL_CALL_RESULT):
            if block := open_tools.get(ev.tool_call_id):
                owner[n] = block
                if ev.type == EventType.TOOL_CALL_ARGS:
                    block.args += ev.delta
                elif ev.type == EventType.TOOL_CALL_RESULT:
                    block.result = ev.content
    return blocks, owner


@dataclass
class Pair:
    left: Block | None
    right: Block | None
    status: str  # same | changed | removed (left only) | added (right only)


def align(a: list[Block], b: list[Block]) -> list[Pair]:
    """Line two block lists up: identical blocks are matched, then what is left in each gap is paired by kind."""
    pairs: list[Pair] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, [x.sig for x in a], [y.sig for y in b], autojunk=False).get_opcodes():
        left, right = a[i1:i2], b[j1:j2]
        if op == "equal":
            pairs += [Pair(x, y, "same") for x, y in zip(left, right)]
            continue
        inner = SequenceMatcher(None, [x.group for x in left], [y.group for y in right], autojunk=False)
        for iop, k1, k2, l1, l2 in inner.get_opcodes():
            if iop == "equal":
                pairs += [Pair(x, y, "changed") for x, y in zip(left[k1:k2], right[l1:l2])]
            else:
                pairs += [Pair(x, None, "removed") for x in left[k1:k2]]
                pairs += [Pair(None, y, "added") for y in right[l1:l2]]
    return pairs


def word_diff(old: str, new: str) -> tuple[Text, Text]:
    """`old` and `new` as styled text: words only in `old` in red, words only in `new` in green."""
    tokens = lambda s: re.findall(r"\s+|\S+", s)  # noqa: E731
    a, b = tokens(old), tokens(new)
    left, right = Text(), Text()
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            left.append("".join(a[i1:i2]))
            right.append("".join(b[j1:j2]))
        else:
            left.append("".join(a[i1:i2]), style="bold #F27C86 on #3A1D20")
            right.append("".join(b[j1:j2]), style="bold #7BD88F on #1D3A24")
    return left, right


# -- drawing one side ------------------------------------------------------------------------


@dataclass(eq=False)
class Pane:
    """Draws one session's items into cells, with the same code that draws a live chat.

    GentuiApp's event handling is borrowed as is, so every widget looks and behaves as it does live. It only needs
    somewhere to mount (`target`, a cell chosen per block), a clock, and the dictionaries a chat keeps."""

    app: "CompareApp"
    session: Session
    root: Any  # where anything outside a block lands
    config: Config
    target: Any = None
    state: dict[str, Any] = field(default_factory=dict)
    item_t: float = 0.0

    def __post_init__(self) -> None:
        self.target = self.root
        self.show_reasoning = self.config.show_reasoning
        self.transcript = Transcript()
        self._reset_chat()

    def _reset_chat(self) -> None:
        self._text_streams: dict[str, MarkdownStream] = {}
        self._thoughts: dict[str, Any] = {}
        self._tool_widgets: dict[str, ToolWidget] = {}
        self._tool_arg_buf: dict[str, str] = {}
        self._singletons: dict[type, ToolWidget] = {}
        self._open_interrupts: dict[str, Any] = {}
        self._answers: dict[str, dict[str, Any]] = {}

    _handle = GentuiApp._handle
    _tool_start = GentuiApp._tool_start
    _on_interrupts = GentuiApp._on_interrupts
    _on_state_changed = GentuiApp._on_state_changed
    _row = GentuiApp._row
    _error = GentuiApp._error
    show_user_message = GentuiApp.show_user_message

    def _log_event(self, ev: Any) -> None:
        """The dev pane is not shown here."""

    def _now(self) -> float:
        return self.item_t

    def _wall(self):
        from datetime import timedelta

        return self.session.recorded_at + timedelta(seconds=self.item_t)

    def notify(self, *args: Any, **kwargs: Any) -> None:  # plugin hooks report problems through the app
        self.app.notify(*args, **kwargs)

    async def mount_chat(self, widget: Any) -> None:
        await self.target.mount(widget)

    _mount = mount_chat

    async def apply(self, item: Item) -> None:
        self.item_t = item.t
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
            if widget := self._tool_widgets.get(approval.get("toolCallId", "")):
                approved = approval.get("decision") == "approve"
                payload: dict[str, Any] = {"approved": approved}
                if approval.get("command"):
                    payload["command"] = approval["command"]
                widget.replay_decision("resolved" if approved else "cancelled", payload)
        elif item.kind == "new":
            self._reset_chat()

    def _show_decision(self, interrupt_id: str, status: str, payload: Any) -> None:
        interrupt = self._open_interrupts.get(interrupt_id)
        widget = self._tool_widgets.get(getattr(interrupt, "tool_call_id", None) or "")
        if widget is None:
            widget = next((w for w in self.root.query(InterruptWidget) if w.interrupt.id == interrupt_id), None)
        if widget is not None:
            widget.replay_decision(status, payload)

    async def finish(self) -> None:
        """Close any message the recording ended in the middle of."""
        for stream in self._text_streams.values():
            await stream.stop()
        self._text_streams.clear()


# -- the app ---------------------------------------------------------------------------------


class DiffScroll(VerticalScroll):
    def anchor(self, *args: Any, **kwargs: Any) -> None:
        """GentuiApp pins its chat to the newest message; a diff is read from the top."""


class CompareApp(GentuiApp):
    READ_ONLY = True
    CSS = (
        GentuiApp.CSS
        + """
    #pickers { height: 3; margin: 0 1; }
    #pickers Select { width: 1fr; margin: 0 1; }
    #prompt-row { height: 3; margin: 0 1; }
    #prompt-row Select { width: 1fr; margin: 0 1; }
    #summary { height: 1; margin: 0 3; }
    .pair { height: auto; }
    .cell { width: 1fr; height: auto; padding: 0 1; border-left: blank; }
    .cell.same { border-left: blank; }
    .cell.removed { border-left: thick $error; background: $error 10%; }
    .cell.added { border-left: thick $success; background: $success 10%; }
    .cell.changed { border-left: thick $warning; background: $warning 8%; }
    .worddiff { display: none; margin: 1 0 0 0; }
    #chat.-words .has-words > .worddiff { display: block; }
    #chat.-words .has-words > .row { display: none; }
    """
    )
    BINDINGS = [
        Binding("m", "toggle_words", "Words / rendered", priority=True),
        Binding("q", "quit", "Quit", priority=True),
    ]

    def __init__(self, sessions: list[Session], config: Config | None = None) -> None:
        config = replace(config or Config(), splash=False, logo=False, show_time=False, dev_pane=False)
        config.url = "compare: " + ", ".join(s.path.stem for s in sessions)
        super().__init__(object(), config)  # no client: nothing is ever sent
        self.sessions = sessions
        self.picked = [0, 1]

    def compose(self) -> ComposeResult:
        options = [(s.path.stem, n) for n, s in enumerate(self.sessions)]
        with Horizontal(id="pickers"):
            yield Select(options, value=0, allow_blank=False, id="pick-left")
            yield Select(options, value=1, allow_blank=False, id="pick-right")
        with Horizontal(id="prompt-row"):
            yield Select([("All prompts", 0)], value=0, allow_blank=False, id="pick-prompt")
        yield Static(id="summary")
        yield DiffScroll(id="chat", classes="-words")
        with Horizontal(id="statusbar"):
            yield Static("m words / rendered · q quit", classes="left")
            yield Static(self.config.target, classes="right")

    async def on_ready(self) -> None:
        await self._rebuild()  # GentuiApp.on_mount (theme, plugins) has run by now

    def action_toggle_dev(self) -> None:
        """There is no event inspector here."""

    def action_toggle_words(self) -> None:
        self.query_one("#chat").toggle_class("-words")

    @on(Select.Changed)
    def _on_pick(self, event: Select.Changed) -> None:
        if event.select.id == "pick-prompt":
            self._show_prompt(event.value)
            return
        picked = [self.query_one("#pick-left", Select).value, self.query_one("#pick-right", Select).value]
        if picked != self.picked and all(isinstance(p, int) for p in picked):
            self.picked = picked
            self.run_worker(self._rebuild(), group="compare", exclusive=True)

    def _show_prompt(self, which: Any) -> None:
        """Show one prompt's exchange (1, 2, ...) or all of them (0)."""
        for row in self.query(".pair"):
            row.display = which == 0 or row.has_class(f"turn-{which}")

    async def _rebuild(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        await chat.remove_children()
        sessions = [self.sessions[n] for n in self.picked]
        both = [blocks_of(s, self.config.show_reasoning) for s in sessions]
        pairs = align(both[0][0], both[1][0])

        panes = [Pane(self, s, chat, self.config) for s in sessions]
        cells: list[dict[int, Vertical]] = [{}, {}]
        rows = []
        turn = 0
        prompt_options: list[tuple[str, int]] = [("All prompts", 0)]
        for pair in pairs:
            user = next((b for b in (pair.left, pair.right) if b is not None and b.kind == "user"), None)
            if user is not None:  # a prompt starts a new turn; what comes before the first one is turn 0
                turn += 1
                text = " ".join(user.text.split())
                prompt_options.append((f"{turn}. {text[:70]}{'…' if len(text) > 70 else ''}", turn))
            row_cells = []
            for side, block in enumerate((pair.left, pair.right)):
                children: list[Static] = []
                classes = "cell"
                if block is None:
                    classes += " empty"
                else:
                    classes += f" {pair.status}"
                    if pair.status == "changed" and block.kind in ("user", "text"):
                        other = pair.right if side == 0 else pair.left
                        old, new = (block.text, other.text) if side == 0 else (other.text, block.text)
                        mark = branding.USER_MARK if block.kind == "user" else branding.MARK
                        shown = word_diff(old, new)[side]
                        children.append(Static(Text(f"{mark} ") + shown, classes="worddiff"))
                        classes += " has-words"
                cell = Vertical(*children, classes=classes)
                if block is not None:
                    cells[side][id(block)] = cell
                row_cells.append(cell)
            rows.append(Horizontal(*row_cells, classes=f"pair turn-{turn}"))
        await chat.mount_all(rows)
        picker = self.query_one("#pick-prompt", Select)
        picker.set_options(prompt_options)
        picker.value = 0

        for side, pane in enumerate(panes):
            owner = both[side][1]
            for n, item in enumerate(pane.session.items):
                if (block := owner.get(n)) is not None:
                    pane.target = cells[side][id(block)]
                await pane.apply(item)
            await pane.finish()

        count = lambda status: sum(p.status == status for p in pairs)  # noqa: E731
        summary = Text()
        summary.append(f"{count('same')} same", style="dim")
        summary.append(f" · {count('changed')} changed", style="yellow")
        summary.append(f" · {count('removed')} only in {sessions[0].path.stem}", style="red")
        summary.append(f" · {count('added')} only in {sessions[1].path.stem}", style="green")
        self.query_one("#summary", Static).update(summary)
        chat.scroll_home(animate=False)  # not where the previous pair of sessions was scrolled to
