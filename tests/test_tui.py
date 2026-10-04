"""Headless TUI test: scripted AG-UI events in, real Textual widgets out."""

import json

from ag_ui.core import (
    RunFinishedEvent, RunStartedEvent, StateDeltaEvent, StateSnapshotEvent,
    TextMessageContentEvent, TextMessageEndEvent, TextMessageStartEvent,
    ToolCallArgsEvent, ToolCallEndEvent, ToolCallResultEvent, ToolCallStartEvent,
)
from textual.widgets import Button, Markdown, Static

from gentui.tui.app import GentuiApp
from gentui.tui.widgets.command import CommandWidget
from gentui.tui.widgets.output import OutputWidget
from gentui.tui.widgets.plan import PlanWidget

CMD = "ls -la"


def tool(call_id, name, args, result=None):
    yield ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name)
    yield ToolCallArgsEvent(tool_call_id=call_id, delta=json.dumps(args))
    yield ToolCallEndEvent(tool_call_id=call_id)
    if result is not None:
        yield ToolCallResultEvent(message_id="m" + call_id, tool_call_id=call_id, content=result, role="tool")


def run_proposal():
    yield RunStartedEvent(thread_id="t", run_id="r1")
    yield StateSnapshotEvent(snapshot={"plan": []})
    yield TextMessageStartEvent(message_id="a1", role="assistant")
    yield TextMessageContentEvent(message_id="a1", delta="Here is a **command**.")
    yield TextMessageEndEvent(message_id="a1")
    yield from tool("c1", "propose_command", {"command": CMD, "explanation": "list files", "risk": "safe"})
    yield RunFinishedEvent(thread_id="t", run_id="r1")


def run_execution():
    yield RunStartedEvent(thread_id="t", run_id="r2")
    yield from tool("c2", "todo_write", {"todos": []})
    yield StateDeltaEvent(delta=[{"op": "replace", "path": "/plan", "value": [
        {"content": "step one", "status": "completed"}, {"content": "step two", "status": "in_progress"}]}])
    yield from tool("c3", "run_command", {"approval_id": "c1"},
                    json.dumps({"command": CMD, "exit_code": 0, "timed_out": False, "truncated": False, "output": "file.txt\n"}))
    yield RunFinishedEvent(thread_id="t", run_id="r2")


class FakeClient:
    def __init__(self):
        self.calls = []
        self.scripts = [run_proposal, run_execution]

    async def run(self, thread_id, text, forwarded_props=None):
        self.calls.append((text, forwarded_props))
        for ev in self.scripts[len(self.calls) - 1]():
            yield ev


async def test_proposal_approval_execution_and_plan():
    client = FakeClient()
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"list files", "enter")
        await pilot.pause(0.5)

        # streamed text became a Markdown message; the tool call became a command widget
        assert any("command" in m.source for m in app.query(Markdown))
        cmd = app.query_one(CommandWidget)
        assert cmd.state == "ready" and not cmd.query_one("#approve", Button).disabled

        await pilot.click("#approve")
        await pilot.pause(0.5)

        # the click was sent back to the backend as the next message + out-of-band approval
        text, props = client.calls[1]
        assert "approval_id=c1" in text  # the model gets an id, never the command text
        assert props["approval"] == {"decision": "approve", "command": CMD, "toolCallId": "c1"}
        assert cmd.state == "approved"

        # run_command rendered as an output widget; the plan was driven by STATE_DELTA
        assert app.query_one(OutputWidget)
        assert "file.txt" in str(app.query_one(OutputWidget).query_one("#output", Static).render())
        plan = app.query_one(PlanWidget)
        assert "1/2" in str(plan.query_one("#body", Static).render())
        assert len(app.query(PlanWidget)) == 1  # updated in place, not duplicated
        assert app.state["plan"][1]["status"] == "in_progress"


async def test_reject_and_edit_flow():
    client = FakeClient()
    client.scripts = [run_proposal, lambda: iter([RunStartedEvent(thread_id="t", run_id="r2"),
                                                  RunFinishedEvent(thread_id="t", run_id="r2")])]
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"x", "enter")
        await pilot.pause(0.5)
        await pilot.click("#edit")
        await pilot.pause(0.1)
        editor = app.query_one(CommandWidget).query_one("#editor")
        assert editor.display and editor.value == CMD
        editor.value = "ls -l"
        await pilot.click("#approve")
        await pilot.pause(0.5)
        assert client.calls[1][1]["approval"]["command"] == "ls -l"  # the EDITED command is approved


async def test_backend_down_shows_error():
    import httpx

    class Down:
        async def run(self, *a, **k):
            raise httpx.ConnectError("refused")
            yield  # pragma: no cover

    app = GentuiApp(Down())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(*"hi", "enter")
        await pilot.pause(0.3)
        assert any("Cannot talk to the backend" in str(s.render()) for s in app.query(".error"))


async def test_blocked_proposal_disables_buttons():
    def blocked_run():
        yield RunStartedEvent(thread_id="t", run_id="r")
        yield from tool("c1", "propose_command", {"command": "rm -rf /", "explanation": "x", "risk": "dangerous"},
                        "BLOCKED: blocked by safety policy: recursive delete. Do not retry it.")
        yield RunFinishedEvent(thread_id="t", run_id="r")

    client = FakeClient()
    client.scripts = [blocked_run]
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("x", "enter")
        await pilot.pause(0.5)
        cmd = app.query_one(CommandWidget)
        assert cmd.state == "blocked"
        assert all(b.disabled for b in cmd.query(Button))


async def test_dev_pane_toggles_with_d_and_logs_events():
    app = GentuiApp(FakeClient())
    async with app.run_test(size=(120, 50)) as pilot:
        dev = app.query_one("#dev")
        assert not dev.has_class("-visible")
        await pilot.press("ctrl+d")
        assert dev.has_class("-visible")
        await pilot.press("x", "enter")
        await pilot.pause(0.5)
        assert len(app.query_one("#events").lines) > 3  # raw AG-UI events were logged


async def test_show_table_widget_renders_rows():
    from textual.widgets import DataTable

    def table_run():
        yield RunStartedEvent(thread_id="t", run_id="r")
        yield from tool("c1", "show_table", {"title": "Files", "columns": ["name", "size"],
                                             "rows": [["a.txt", "1"], ["b.txt", "2"]]})
        yield RunFinishedEvent(thread_id="t", run_id="r")

    client = FakeClient()
    client.scripts = [table_run]
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("x", "enter")
        await pilot.pause(0.5)
        table = app.query_one(DataTable)
        assert table.row_count == 2 and len(table.columns) == 2


async def test_unknown_tool_falls_back_to_generic_card():
    from gentui.tui.widgets.generic import GenericToolWidget

    def run():
        yield RunStartedEvent(thread_id="t", run_id="r")
        yield from tool("c1", "some_new_tool", {"a": 1}, "done")
        yield RunFinishedEvent(thread_id="t", run_id="r")

    client = FakeClient()
    client.scripts = [run]
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("x", "enter")
        await pilot.pause(0.5)
        assert app.query_one(GenericToolWidget).args == {"a": 1}
