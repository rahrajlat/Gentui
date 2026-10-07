"""The /new and /export_md slash commands, and the transcript behind /export_md."""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from ag_ui.core import (
    Interrupt, ReasoningEndEvent, ReasoningMessageContentEvent, ReasoningMessageEndEvent,
    ReasoningMessageStartEvent, ReasoningStartEvent, RunErrorEvent, RunFinishedEvent,
    RunFinishedInterruptOutcome, RunStartedEvent, TextMessageContentEvent, TextMessageEndEvent,
    TextMessageStartEvent, ToolCallArgsEvent, ToolCallEndEvent, ToolCallResultEvent, ToolCallStartEvent,
)
from textual.widgets import Markdown, Static

from gentui.config import Config
from gentui.tui.app import GentuiApp
from gentui.tui.commands import export_path
from gentui.tui.transcript import Transcript, fence


def tool(call_id, name, args, result=None):
    yield ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name)
    yield ToolCallArgsEvent(tool_call_id=call_id, delta=json.dumps(args))
    yield ToolCallEndEvent(tool_call_id=call_id)
    if result is not None:
        yield ToolCallResultEvent(message_id="m" + call_id, tool_call_id=call_id, content=result, role="tool")


def say(mid, text):
    yield TextMessageStartEvent(message_id=mid, role="assistant")
    yield TextMessageContentEvent(message_id=mid, delta=text)
    yield TextMessageEndEvent(message_id=mid)


def think(text):
    yield ReasoningStartEvent(message_id="r1")
    yield ReasoningMessageStartEvent(message_id="r1", role="reasoning")
    yield ReasoningMessageContentEvent(message_id="r1", delta=text)
    yield ReasoningMessageEndEvent(message_id="r1")
    yield ReasoningEndEvent(message_id="r1")


class Scripted:
    """Run N replays script N (the last script repeats)."""

    def __init__(self, *scripts):
        self.scripts, self.calls = scripts, []

    async def run(self, thread_id, text, forwarded_props=None, resume=None):
        self.calls.append((thread_id, text, resume))
        for ev in self.scripts[min(len(self.calls), len(self.scripts)) - 1]():
            yield ev


async def send(pilot, text, wait=0.5):
    await pilot.press(*text, "enter")
    await pilot.pause(wait)


def only_md(folder):
    files = sorted(folder.glob("*.md"))
    assert len(files) == 1, files
    return files[0]


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- /new ------------------------------------------------------------------------------------------


async def test_new_starts_a_fresh_chat_but_keeps_the_logo_and_welcome(cwd):
    app = GentuiApp(Scripted(lambda: [*say("a", "hello there"), RunFinishedEvent(thread_id="t", run_id="r")]), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "hi")
        assert app.query(".user") and app.transcript
        thread = app.thread_id
        await send(pilot, "/new", 0.3)
        assert not app.query(".user") and not app.query(Markdown)
        assert app.query("#brand") and app.query("#welcome")
        assert app.thread_id != thread
        assert not app.transcript  # the old chat is not carried over


async def test_clear_is_the_same_as_new(cwd):
    app = GentuiApp(Scripted(lambda: [RunFinishedEvent(thread_id="t", run_id="r")]), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "hi")
        thread = app.thread_id
        await send(pilot, "/clear", 0.3)
        assert not app.query(".user") and app.thread_id != thread


async def test_new_stops_an_answer_in_flight_and_nothing_leaks_into_the_new_chat(cwd):
    gate = asyncio.Event()

    class Slow:
        def __init__(self):
            self.calls = 0

        async def run(self, thread_id, text, forwarded_props=None, resume=None):
            self.calls += 1
            if self.calls == 1:
                yield RunStartedEvent(thread_id=thread_id, run_id="r1")
                await gate.wait()  # the old answer is still being written when /new is typed
                for ev in say("old", "OLD ANSWER"):
                    yield ev
                yield RunFinishedEvent(thread_id=thread_id, run_id="r1")
            else:
                for ev in say("new", "NEW ANSWER"):
                    yield ev
                yield RunFinishedEvent(thread_id=thread_id, run_id="r2")

    app = GentuiApp(Slow(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "first question", 0.4)
        assert app._busy
        await send(pilot, "/new", 0.4)
        assert not app._busy and not app.query(".user")
        gate.set()  # the old run would now continue writing
        await pilot.pause(0.5)
        assert not any("OLD ANSWER" in m.source for m in app.query(Markdown))
        assert not app.transcript

        await send(pilot, "second question", 0.8)  # the new chat works normally
        assert any("NEW ANSWER" in m.source for m in app.query(Markdown))
        assert not any("OLD ANSWER" in m.source for m in app.query(Markdown))
        assert not app._busy


async def test_new_drops_messages_waiting_for_their_turn(cwd):
    gate = asyncio.Event()
    received = []

    class Slow:
        async def run(self, thread_id, text, forwarded_props=None, resume=None):
            received.append(text)
            await gate.wait()
            yield RunFinishedEvent(thread_id=thread_id, run_id="r")

    app = GentuiApp(Slow(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "one", 0.3)
        await send(pilot, "two", 0.3)  # queued behind the first
        await send(pilot, "/new", 0.4)
        gate.set()
        await pilot.pause(0.4)
    assert received == ["one"]


# -- /export_md ----------------------------------------------------------------------------------------


def proposal_run():
    yield RunStartedEvent(thread_id="t", run_id="r1")
    yield from think("The user wants the biggest files, so I should propose a find command.")
    yield from say("a1", "Here is a command:")
    yield from tool("c1", "propose_command", {"command": "ls -S | head -3", "explanation": "biggest", "risk": "safe"},
                    "Proposal shown to the user. It has NOT been run.")
    yield RunFinishedEvent(thread_id="t", run_id="r1", outcome=RunFinishedInterruptOutcome(interrupts=[
        Interrupt(id="approve-c1", reason="tool_call", tool_call_id="c1", message="Run?")]))


def execution_run():
    yield RunStartedEvent(thread_id="t", run_id="r2")
    yield from tool("c2", "run_command", {"approval_id": "c1"},
                    json.dumps({"command": "ls -S | head -3", "exit_code": 0, "output": "big.bin\nmid.txt\n"}))
    yield from say("a2", "The biggest file is **big.bin**.")
    yield RunFinishedEvent(thread_id="t", run_id="r2")


async def test_export_writes_the_whole_conversation_as_markdown(cwd):
    app = GentuiApp(Scripted(proposal_run, execution_run), Config(splash=False, agentcore_arn=None, url="http://backend/agent"))
    async with app.run_test(size=(120, 50)) as pilot:
        await send(pilot, "what are the biggest files?")
        app.query_one("#approve").press()
        await pilot.pause(0.6)
        await send(pilot, "/export_md", 0.4)
        thread = app.thread_id

    text = only_md(cwd).read_text(encoding="utf-8")
    assert text.startswith("# Gentui conversation")
    assert "| Backend | `http://backend/agent` |" in text and f"| Thread | `{thread}` |" in text
    assert re.search(r"\| Exported \| \d{4}-\d\d-\d\d \d\d:\d\d \|", text)
    assert re.search(r"## You · \d\d:\d\d\n\nwhat are the biggest files\?", text)
    assert re.search(r"## Assistant · \d\d:\d\d\n\nHere is a command:", text)
    assert "<summary>◈ Thought for" in text and "propose a find command" in text
    assert "**Tool call:** `propose_command`" in text and '"command": "ls -S | head -3"' in text
    assert re.search(r"> \*\*Approved\*\* · \d\d:\d\d", text)
    assert "**Tool call:** `run_command`" in text and "big.bin" in text
    assert "The biggest file is **big.bin**." in text
    # in the order it happened
    order = [text.index(s) for s in ("what are the biggest", "Here is a command", "propose_command", "Approved", "run_command", "The biggest file is")]
    assert order == sorted(order)


async def test_rejecting_and_editing_are_recorded(cwd):
    from gentui.tui.widgets.base import ToolWidget

    app = GentuiApp(Scripted(proposal_run, lambda: [RunFinishedEvent(thread_id="t", run_id="r")]), Config(splash=False))
    async with app.run_test(size=(120, 50)) as pilot:
        await send(pilot, "go")
        app.query_one("#reject").press()
        await pilot.pause(0.4)
        app.post_message(ToolWidget.Answer("not-open", "resolved", {"approved": True}))  # not an open interrupt: ignored
        await pilot.pause(0.2)
        await send(pilot, "/export_md", 0.3)
    assert "> **Rejected**" in only_md(cwd).read_text(encoding="utf-8")

    transcript = Transcript()
    app2 = GentuiApp(Scripted(), Config(splash=False))
    app2.transcript = transcript
    app2._record_decision(ToolWidget.Answer("i", "resolved", {"approved": True, "command": "ls -l"}))
    assert "Approved (edited to `ls -l`)" == transcript.entries[-1]["text"]


async def test_errors_are_exported(cwd):
    app = GentuiApp(Scripted(lambda: [RunStartedEvent(thread_id="t", run_id="r"), RunErrorEvent(message="backend exploded")]), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "hi")
        await send(pilot, "/export_md", 0.3)
    assert re.search(r"> \*\*Error:\*\* backend exploded · \d\d:\d\d", only_md(cwd).read_text(encoding="utf-8"))


async def test_a_show_table_call_becomes_a_markdown_table(cwd):
    run = lambda: [*tool("t1", "show_table", {"title": "Files", "columns": ["name", "size"], "rows": [["a|b", "1"], ["c", "2"]]}),
                   RunFinishedEvent(thread_id="t", run_id="r")]
    app = GentuiApp(Scripted(run), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "table")
        await send(pilot, "/export_md", 0.3)
    text = only_md(cwd).read_text(encoding="utf-8")
    assert "| name | size |" in text and "|---|---|" in text and "| a\\|b | 1 |" in text and "*Files*" in text


async def test_output_containing_code_fences_cannot_break_the_file(cwd):
    nasty = "before\n```python\nprint('x')\n```\nafter"
    run = lambda: [*tool("c", "run_command", {"approval_id": "x"}, nasty), RunFinishedEvent(thread_id="t", run_id="r")]
    app = GentuiApp(Scripted(run), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "go")
        await send(pilot, "/export_md", 0.3)
    text = only_md(cwd).read_text(encoding="utf-8")
    assert "````\nbefore" in text and "after\n````" in text  # a longer fence wraps the inner one
    assert fence("a ``` b") == "````\na ``` b\n````"


async def test_exporting_an_empty_chat_writes_nothing(cwd):
    app = GentuiApp(Scripted(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "/export_md", 0.3)
    assert list(cwd.glob("*.md")) == []


async def test_export_after_new_is_empty(cwd):
    app = GentuiApp(Scripted(lambda: [*say("a", "hi"), RunFinishedEvent(thread_id="t", run_id="r")]), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "hello")
        await send(pilot, "/new", 0.3)
        await send(pilot, "/export_md", 0.3)
    assert list(cwd.glob("*.md")) == []


async def test_export_path_argument_file_folder_and_no_overwrite(cwd):
    app = GentuiApp(Scripted(lambda: [*say("a", "hi"), RunFinishedEvent(thread_id="t", run_id="r")]), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "hello")
        await send(pilot, "/export_md notes", 0.3)             # no extension: .md is added
        await send(pilot, "/export_md notes.md", 0.3)          # exists already: never overwritten
        await send(pilot, "/export_md exports/deep/chat.md", 0.3)  # missing folders are created
        await send(pilot, "/export_md out/", 0.3)              # a folder: a timestamped file inside
        (cwd / "existing").mkdir()
        await send(pilot, "/export_md existing", 0.3)          # an existing folder, no trailing slash
    assert (cwd / "notes.md").exists() and (cwd / "notes-1.md").exists()
    assert (cwd / "exports" / "deep" / "chat.md").exists()
    assert len(list((cwd / "out").glob("gentui-chat-*.md"))) == 1
    assert len(list((cwd / "existing").glob("gentui-chat-*.md"))) == 1
    for f in (cwd / "notes.md", cwd / "notes-1.md"):  # both are complete copies of the chat
        assert "## You" in f.read_text(encoding="utf-8") and "hello" in f.read_text(encoding="utf-8")


async def test_two_default_exports_in_the_same_second_do_not_collide(cwd):
    app = GentuiApp(Scripted(lambda: [*say("a", "hi"), RunFinishedEvent(thread_id="t", run_id="r")]), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "hello")
        await send(pilot, "/export_md", 0.2)
        await send(pilot, "/export_md", 0.2)
    assert len(list(cwd.glob("gentui-chat-*.md"))) == 2


async def test_an_unwritable_destination_is_reported_not_a_crash(cwd):
    (cwd / "afile").write_text("x")
    app = GentuiApp(Scripted(lambda: [*say("a", "hi"), RunFinishedEvent(thread_id="t", run_id="r")]), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "hello")
        await send(pilot, "/export_md afile/inside.md", 0.3)  # "afile" is a file, so it cannot be a folder
        assert app.is_running and app.query(".user")


def test_export_path_rules(cwd):
    now = datetime(2026, 10, 7, 14, 30, 5)
    name = "gentui-chat-20261007-143005.md"
    assert export_path("", now) == cwd / name
    assert export_path("  ", now) == cwd / name
    assert export_path("notes", now).name == "notes.md"
    assert export_path("notes.txt", now).name == "notes.txt"  # an explicit extension is respected
    assert export_path("some/dir/", now) == Path("some/dir") / name
    assert export_path('"quoted.md"', now).name == "quoted.md"
    assert export_path("~/x", now).is_absolute()


async def test_help_lists_the_new_commands(cwd):
    app = GentuiApp(Scripted(), Config(splash=False))
    async with app.run_test(size=(120, 40)) as pilot:
        await send(pilot, "/help", 0.3)
        text = " ".join(str(s.render()) for s in app.query(".welcome"))
    assert "/new" in text and "/export_md" in text


# -- the keyboard shortcuts are gone; the slash commands do the work ----------------------------------------------


async def test_ctrl_q_and_ctrl_d_no_longer_do_anything(cwd):
    app = GentuiApp(Scripted(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("ctrl+q")  # Textual binds this to quit by default; Gentui switches it off
        await pilot.pause(0.3)
        assert app.is_running
        await pilot.press("ctrl+d")
        await pilot.pause(0.2)
        assert not app.query_one("#dev").has_class("-visible")


async def test_quit_command_exits(cwd):
    app = GentuiApp(Scripted(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await send(pilot, "/quit", 0.4)
    assert not app.is_running


async def test_dev_command_toggles_the_inspector_on_and_off(cwd):
    app = GentuiApp(Scripted(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        dev = app.query_one("#dev")
        await send(pilot, "/dev", 0.2)
        assert dev.has_class("-visible")
        await send(pilot, "/dev", 0.2)
        assert not dev.has_class("-visible")


async def test_ctrl_c_points_to_the_quit_command(cwd):
    app = GentuiApp(Scripted(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("ctrl+c")
        await pilot.pause(0.3)
        assert app.is_running
        assert any("/quit" in n.message for n in app._notifications)
        assert not any("ctrl+q" in n.message.lower() for n in app._notifications)


async def test_screen_hints_name_the_slash_commands_not_the_old_keys(cwd):
    app = GentuiApp(Scripted(), Config(splash=False))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        hints = str(app.query_one("#statusbar .left").render())
        welcome = str(app.query_one("#welcome", Static).render())
    for text in (hints, welcome):
        assert "/quit" in text and "/dev" in text.replace("/dev ", "/dev") and "ctrl" not in text.lower()
