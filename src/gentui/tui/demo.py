"""`gentui --demo`: a self-playing tour of every feature, driven by a scripted backend (no agent, no network).

A `Director` types into the prompt, presses Approve and runs slash commands like a user would, while a
`DemoClient` streams canned AG-UI events back. Pick a scene up front (`gentui --demo approval`, or the menu from
a bare `gentui --demo`) or in the app with `/demo <scene>`.
"""

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import (
    Event, Interrupt, ReasoningEndEvent, ReasoningMessageContentEvent, ReasoningMessageEndEvent,
    ReasoningMessageStartEvent, ReasoningStartEvent, RunFinishedEvent, RunFinishedInterruptOutcome,
    RunStartedEvent, StateDeltaEvent, StateSnapshotEvent, TextMessageContentEvent, TextMessageEndEvent,
    TextMessageStartEvent, ToolCallArgsEvent, ToolCallEndEvent, ToolCallResultEvent, ToolCallStartEvent,
)
from textual import events
from textual.widgets import Input, Static

from gentui.plugins import register_command
from gentui.tui.app import GentuiApp

FALLBACK = "This is **demo mode**: the replies are scripted. Try `/demo` to pick a scene, or `/quit` to leave."


# -- building turns (one backend run each) ------------------------------------------------------


def tool(call_id: str, name: str, args: dict, result: str | None = None) -> list[Event]:
    out: list[Event] = [
        ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name),
        ToolCallArgsEvent(tool_call_id=call_id, delta=json.dumps(args)),
        ToolCallEndEvent(tool_call_id=call_id),
    ]
    if result is not None:
        out.append(ToolCallResultEvent(message_id="m" + call_id, tool_call_id=call_id, content=result, role="tool"))
    return out


def say(mid: str, text: str) -> list[Event]:
    return [TextMessageStartEvent(message_id=mid, role="assistant"),
            TextMessageContentEvent(message_id=mid, delta=text), TextMessageEndEvent(message_id=mid)]


def think(text: str) -> list[Event]:
    return [ReasoningStartEvent(message_id="r"), ReasoningMessageStartEvent(message_id="r", role="reasoning"),
            ReasoningMessageContentEvent(message_id="r", delta=text), ReasoningMessageEndEvent(message_id="r"),
            ReasoningEndEvent(message_id="r")]


def plan(*states: str) -> list[dict]:
    items = ["check the python version", "check disk usage", "summarise"]
    return [{"content": c, "status": s} for c, s in zip(items, states)]


def run(n: int, *body: list[Event], interrupt: str | None = None) -> list[Event]:
    """One run's events. With `interrupt` (a tool call id) the run ends waiting for an approval."""
    outcome = None
    if interrupt:
        outcome = RunFinishedInterruptOutcome(interrupts=[Interrupt(
            id=f"approve-{interrupt}", reason="tool_call", tool_call_id=interrupt, message="Run this command?")])
    finish = RunFinishedEvent(thread_id="demo", run_id=f"r{n}", outcome=outcome) if outcome else \
        RunFinishedEvent(thread_id="demo", run_id=f"r{n}")
    return [RunStartedEvent(thread_id="demo", run_id=f"r{n}"), *(e for part in body for e in part), finish]


class DemoClient:
    """Plays the turns the Director queues, streaming them like a live backend."""

    def __init__(self, speed: float = 1.0) -> None:
        self.speed = speed
        self.turns: deque[list[Event]] = deque()
        self.on_raw = None

    async def _pause(self, seconds: float) -> None:
        await asyncio.sleep(seconds / self.speed)

    async def run(self, thread_id: str, text: str, forwarded_props: dict[str, Any] | None = None,
                  resume: list[dict[str, Any]] | None = None) -> AsyncIterator[Event]:
        turn = self.turns.popleft() if self.turns else run(0, say("fallback", FALLBACK))
        for event in turn:
            for piece in self._chunks(event):
                if self.on_raw:
                    self.on_raw(piece.model_dump_json(by_alias=True, exclude_none=True))
                yield piece
                await self._pause(0.04 if isinstance(piece, (TextMessageContentEvent, ReasoningMessageContentEvent)) else 0.25)

    @staticmethod
    def _chunks(event: Event) -> list[Event]:
        """Split long text into word-sized deltas so it streams in."""
        if isinstance(event, (TextMessageContentEvent, ReasoningMessageContentEvent)) and len(event.delta) > 12:
            words = event.delta.split(" ")
            parts = [" ".join(words[i:i + 2]) + (" " if i + 2 < len(words) else "") for i in range(0, len(words), 2)]
            return [event.model_copy(update={"delta": p}) for p in parts]
        return [event]


# -- the scenes ---------------------------------------------------------------------------------
# Steps: ("caption", text) | ("ask", prompt, turn) | ("approve", turn) | ("cmd", "/slash") | ("pause", seconds)

CMD = "python3 --version && df -h / | tail -1"
MOUNTS = ["/var/lib/docker", "/", "/home", "/boot", "/run"]
PCT = [91, 78, 64, 22, 3]


def _chat() -> list[tuple]:
    return [
        ("caption", "Streaming chat, with the model's chain of thought"),
        ("ask", "what can you help me with?", run(
            1, think("The user is new here. Give a short, friendly overview with a list and one example."),
            say("a1", "I'm a **demo agent**. Everything you see is scripted, but it is real AG-UI:\n\n"
                      "- streamed *Markdown* answers\n- a collapsible chain of thought\n"
                      "- tool calls drawn as widgets (commands, tables, charts, plans)\n\n"
                      "```bash\ngentui http://localhost:8000/agent\n```"))),
    ]


def _approval() -> list[tuple]:
    return [
        ("caption", "Memory recall, a live plan and human approval"),
        ("ask", "is this box healthy? check python and disk", run(
            1, think("Two checks: the Python version, then disk usage. I'll plan it and propose one command."),
            tool("m1", "search_memory", {"query": "disk usage threshold"}, "User prefers alerts above 85% full."),
            [StateSnapshotEvent(snapshot={"plan": plan("in_progress", "pending", "pending")})],
            say("a1", "Starting with the **Python version** and root disk usage."),
            tool("c1", "propose_command", {"command": CMD, "explanation": "Prints the Python version and root disk usage.",
                                           "risk": "safe"},
                 "Proposal shown to the user. It has NOT been run. Stop and wait for the user's decision."),
            interrupt="c1")),
        ("caption", "Nothing runs until you click Approve"),
        ("pause", 2.5),
        ("approve", run(
            2, tool("c2", "run_command", {"approval_id": "c1"}, json.dumps({
                "command": CMD, "exit_code": 0, "timed_out": False, "truncated": False,
                "output": "Python 3.12.4\n/dev/nvme0n1p2  200G  156G   44G  78% /\n"})),
            [StateDeltaEvent(delta=[{"op": "replace", "path": "/plan", "value": plan("completed", "completed", "in_progress")}])],
            say("a2", "Python is **3.12.4** and `/` is **78%** full: healthy, under your 85% threshold."),
            [StateDeltaEvent(delta=[{"op": "replace", "path": "/plan", "value": plan("completed", "completed", "completed")}])])),
    ]


def _widgets() -> list[tuple]:
    return [
        ("caption", "Tables and charts from tool calls"),
        ("ask", "show disk usage per mount as a table, then a chart", run(
            1, tool("t1", "show_table", {"title": "Disk usage", "columns": ["Mount", "Used %", "Size"],
                                         "rows": [[m, f"{p}%", s] for m, p, s in zip(MOUNTS, PCT, ["120G", "200G", "500G", "1G", "16G"])]}, "ok"),
            tool("c3", "show_chart", {"type": "bar", "title": "Used % per mount", "x": MOUNTS,
                                      "series": [{"name": "Used %", "values": PCT}], "y_label": "%"}, "ok"),
            say("a3", "Same data twice. `/var/lib/docker` stands out. Charts can also be line, scatter or histogram."))),
    ]


def _devtools() -> list[tuple]:
    return [
        ("caption", "/dev shows the raw AG-UI events, exactly as sent"),
        ("cmd", "/dev"), ("pause", 3.5), ("cmd", "/dev"),
        ("caption", "Themes: /theme lists them, /theme <name> switches"),
        ("cmd", "/theme"), ("pause", 1.5), ("cmd", "/theme dracula"), ("pause", 2.5), ("cmd", "/theme gentui"),
    ]


SCENES: dict[str, tuple[str, Any]] = {
    "all": ("The whole movie: every feature, start to finish", None),
    "chat": ("Streaming Markdown and the chain of thought", _chat),
    "approval": ("Memory, a live plan, human-in-the-loop approval, command output", _approval),
    "widgets": ("Generative widgets: a table and a chart", _widgets),
    "devtools": ("The event inspector (/dev) and themes", _devtools),
}


def script(name: str) -> list[tuple]:
    if name != "all":
        return SCENES[name][1]()
    steps: list[tuple] = [("caption", "Gentui: bring your agent, speak AG-UI"), ("cmd", "/help"), ("pause", 2.5)]
    for part in ("chat", "approval", "widgets", "devtools"):
        steps += [("cmd", "/new"), ("pause", 0.8), *SCENES[part][1]()]
        steps.append(("pause", 2.0))
    return steps + [("caption", "pip install gentui  ·  github.com/rahrajlat/Gentui")]


# -- the director -------------------------------------------------------------------------------


class DemoApp(GentuiApp):
    """The normal app plus a Director that plays a scene once it is up."""

    def __init__(self, client: DemoClient, config, scene: str = "all") -> None:
        super().__init__(client, config)
        self.scene = scene

    def on_ready(self, event: events.Ready) -> None:
        self.start_demo(self.scene)

    def start_demo(self, scene: str) -> None:
        self.workers.cancel_group(self, "demo")
        self.run_worker(self._play(scene), group="demo")

    def _caption(self, text: str, seconds: float = 4) -> None:
        self.notify(text, title="Demo", timeout=seconds)

    async def _idle(self) -> None:
        await asyncio.sleep(0.3)
        while self._busy:
            await asyncio.sleep(0.1)

    async def _type(self, text: str) -> None:
        prompt = self.query_one("#prompt", Input)
        speed = self.client.speed
        for i in range(1, len(text) + 1):
            prompt.value = text[:i]
            await asyncio.sleep(0.045 / speed)
        await asyncio.sleep(0.4 / speed)
        await prompt.action_submit()

    async def _play(self, scene: str) -> None:
        pause = lambda s: asyncio.sleep(s / self.client.speed)  # noqa: E731
        while len(self.screen_stack) > 1:  # let the splash finish
            await asyncio.sleep(0.1)
        await pause(1.0)
        for step in script(scene):
            match step:
                case ("caption", text):
                    self._caption(text)
                case ("pause", seconds):
                    await pause(seconds)
                case ("cmd", text):
                    await self._type(text)
                    await pause(1.0)
                case ("ask", text, turn):
                    self.client.turns.append(turn)
                    await self._type(text)
                    await self._idle()
                    await pause(1.5)
                case ("approve", turn):
                    self.client.turns.append(turn)
                    while not self.query("#approve"):
                        await asyncio.sleep(0.1)
                    self.query("#approve").last().press()
                    await self._idle()
                    await pause(1.5)
        self._caption("Demo finished. /demo to pick another scene, /quit to leave.", seconds=8)


def scene_list() -> str:
    return "\n".join(f"  {name:<9} {desc}" for name, (desc, _) in SCENES.items())


@register_command("demo", "demo mode: /demo <scene> (no name = list the scenes)")
async def demo(app, args: str) -> None:
    name = args.strip()
    if not isinstance(app, DemoApp):
        app.notify("Start Gentui with --demo to use this", severity="warning")
    elif name in SCENES:
        app.start_demo(name)
    else:
        if name:
            app.notify(f"unknown scene {name!r}", severity="warning")
        await app.mount_chat(Static("scenes:\n" + scene_list(), classes="welcome"))


def choose_scene(stdin=None, out=print) -> str:
    """The menu shown by a bare `gentui --demo`. Not a terminal (a pipe, CI): the whole movie."""
    import sys

    stdin = stdin or sys.stdin
    names = list(SCENES)
    if not stdin.isatty():
        return "all"
    out("Gentui demo. What would you like to watch?\n")
    for i, name in enumerate(names, 1):
        out(f"  {i}. {name:<9} {SCENES[name][0]}")
    while True:
        answer = input("\nChoose 1-%d or a name [1]: " % len(names)).strip().lower()
        if not answer:
            return names[0]
        if answer in SCENES:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        out("Not one of the scenes.")
