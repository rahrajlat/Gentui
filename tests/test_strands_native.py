"""The in-process Strands adapter: a real Strands Agent driven by a scripted model (no AWS, no network)."""

import asyncio
import sys

import pytest
from ag_ui.core import EventType as T
from textual.widgets import Button, Markdown

from gentui import GentUI
from gentui.adapters.strands import StrandsAGUIAdapter, StrandsTranslator, approval_hook
from gentui.tui.widgets.generic import GenericToolWidget
from gentui.tui.widgets.interrupt import InterruptWidget

strands = pytest.importorskip("strands")
from strands import Agent, tool  # noqa: E402
from strands.models import Model  # noqa: E402


class ScriptedModel(Model):
    """Each call to the model plays the next script (a list of Bedrock-style stream events)."""

    def __init__(self, *scripts):
        self.scripts = list(scripts)

    def update_config(self, **kwargs): ...
    def get_config(self):
        return {}

    async def structured_output(self, *a, **k):
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        for e in self.scripts.pop(0):
            yield e


def text(*chunks):
    return [{"messageStart": {"role": "assistant"}}] + [
        {"contentBlockDelta": {"delta": {"text": c}, "contentBlockIndex": 0}} for c in chunks
    ] + [{"contentBlockStop": {"contentBlockIndex": 0}}, {"messageStop": {"stopReason": "end_turn"}}]


def calls(*specs, thought=None):
    """A model turn that requests tools: specs are (id, name, [arg chunks])."""
    out = [{"messageStart": {"role": "assistant"}}]
    index = 0
    if thought:
        out += [{"contentBlockDelta": {"delta": {"reasoningContent": {"text": thought}}, "contentBlockIndex": 0}},
                {"contentBlockStop": {"contentBlockIndex": 0}}]
        index = 1
    for i, (call_id, name, chunks) in enumerate(specs, start=index):
        out.append({"contentBlockStart": {"start": {"toolUse": {"toolUseId": call_id, "name": name}}, "contentBlockIndex": i}})
        out += [{"contentBlockDelta": {"delta": {"toolUse": {"input": c}}, "contentBlockIndex": i}} for c in chunks]
        out.append({"contentBlockStop": {"contentBlockIndex": i}})
    return out + [{"messageStop": {"stopReason": "tool_use"}}]


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def boom() -> str:
    """Always fails."""
    raise ValueError("kaput")


@tool
def delete_file(path: str) -> str:
    """Delete a file."""
    DELETED.append(path)
    return f"deleted {path}"


DELETED: list[str] = []


def make(*scripts, tools=(add,), hooks=()):
    return Agent(model=ScriptedModel(*scripts), tools=list(tools), callback_handler=None, hooks=list(hooks))


def shown(widget) -> str:
    """The text a tool card displays (its body is a rich Group, which str() alone does not expand)."""
    from rich.console import Console

    console = Console(record=True, width=200, file=open("/dev/null", "w"))
    console.print(widget.query_one("#body").visual._renderable)
    return console.export_text()


async def collect(adapter, text="hi", thread="t", resume=None):
    return [ev async for ev in adapter.run(thread, text, None, resume)]


def types(events):
    return [e.type for e in events]


def body(events, kind):
    return "".join(e.delta for e in events if e.type == kind)


# -- conversion -------------------------------------------------------------------------------


async def test_text_streams_once_with_stable_ids():
    events = await collect(StrandsAGUIAdapter(make(text("Hel", "lo ", "there"))))
    assert types(events) == [T.RUN_STARTED, T.TEXT_MESSAGE_START, *[T.TEXT_MESSAGE_CONTENT] * 3, T.TEXT_MESSAGE_END, T.RUN_FINISHED]
    assert body(events, T.TEXT_MESSAGE_CONTENT) == "Hello there"  # not doubled by Strands' convenience events
    assert len({getattr(e, "message_id", None) for e in events[1:-1]}) == 1


async def test_tool_lifecycle_args_result_and_following_answer():
    agent = make(calls(("c1", "add", ['{"a": ', "2, ", '"b": 3}'])), text("It is 5"))
    events = await collect(StrandsAGUIAdapter(agent))
    assert types(events) == [
        T.RUN_STARTED, T.TOOL_CALL_START, T.TOOL_CALL_ARGS, T.TOOL_CALL_ARGS, T.TOOL_CALL_ARGS, T.TOOL_CALL_END,
        T.TOOL_CALL_RESULT, T.TEXT_MESSAGE_START, T.TEXT_MESSAGE_CONTENT, T.TEXT_MESSAGE_END, T.RUN_FINISHED,
    ]
    assert events[1].tool_call_name == "add" and events[1].tool_call_id == "c1"
    assert body(events, T.TOOL_CALL_ARGS) == '{"a": 2, "b": 3}'
    result = next(e for e in events if e.type == T.TOOL_CALL_RESULT)
    assert (result.tool_call_id, result.content, result.raw_event) == ("c1", "5", {"status": "success"})


async def test_several_tool_calls_in_one_turn_keep_their_own_ids_and_results():
    agent = make(calls(("c1", "add", ['{"a":1,"b":1}']), ("c2", "add", ['{"a":2,"b":2}'])), text("done"))
    events = await collect(StrandsAGUIAdapter(agent))
    starts = [e.tool_call_id for e in events if e.type == T.TOOL_CALL_START]
    results = {e.tool_call_id: e.content for e in events if e.type == T.TOOL_CALL_RESULT}
    assert starts == ["c1", "c2"] and results == {"c1": "2", "c2": "4"}
    first_result = next(i for i, e in enumerate(events) if e.type == T.TOOL_CALL_RESULT)
    assert all(e.type != T.TOOL_CALL_START for e in events[first_result:])  # started, then ran


async def test_tool_failure_is_flagged_not_hidden():
    events = await collect(StrandsAGUIAdapter(make(calls(("c1", "boom", [])), text("sorry"), tools=(boom,))))
    result = next(e for e in events if e.type == T.TOOL_CALL_RESULT)
    assert result.raw_event == {"status": "error"} and "kaput" in result.content
    assert T.RUN_ERROR not in types(events) and types(events)[-1] == T.RUN_FINISHED


async def test_reasoning_is_separate_from_tool_planning_and_answer():
    agent = make(calls(("c1", "add", ['{"a":1,"b":2}']), thought="need to add"), text("3"))
    events = await collect(StrandsAGUIAdapter(agent))
    kinds = types(events)
    assert body(events, T.REASONING_MESSAGE_CONTENT) == "need to add"
    assert kinds.index(T.REASONING_END) < kinds.index(T.TOOL_CALL_START)
    assert body(events, T.TEXT_MESSAGE_CONTENT) == "3"


async def test_no_reasoning_events_when_the_model_has_none():
    events = await collect(StrandsAGUIAdapter(make(text("plain"))))
    assert not any(t.name.startswith("REASONING") for t in types(events))


async def test_no_argument_tool_has_no_args_event():
    events = await collect(StrandsAGUIAdapter(make(calls(("c1", "boom", [])), text("x"), tools=(boom,))))
    assert T.TOOL_CALL_ARGS not in types(events)


def test_incomplete_stream_is_closed_cleanly():
    tr = StrandsTranslator()
    out = list(tr.translate({"event": {"contentBlockDelta": {"delta": {"text": "half"}}}}))
    out += list(tr.translate({"event": {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "x", "name": "t"}}}}}))
    out += list(tr.close())
    assert types(out) == [T.TEXT_MESSAGE_START, T.TEXT_MESSAGE_CONTENT, T.TEXT_MESSAGE_END, T.TOOL_CALL_START, T.TOOL_CALL_END]


def test_sub_agent_tool_calls_surface_but_its_chat_stays_hidden():
    tr = StrandsTranslator()
    wrap = lambda data: {"type": "tool_stream", "tool_stream_event": {"tool_use": {"toolUseId": "p"}, "data": data}}
    out = list(tr.translate(wrap({"event": {"contentBlockDelta": {"delta": {"text": "inner chatter"}}}})))
    out += list(tr.translate(wrap({"event": {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "i", "name": "show_table"}}}}})))
    assert types(out) == [T.TOOL_CALL_START]


# -- failures, cancellation, multi-turn -------------------------------------------------------


async def test_model_failure_becomes_run_error_after_closing_open_blocks():
    class Broken(ScriptedModel):
        async def stream(self, *a, **k):
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockDelta": {"delta": {"text": "par"}, "contentBlockIndex": 0}}
            raise RuntimeError("model down")

    events = await collect(StrandsAGUIAdapter(Agent(model=Broken(), callback_handler=None)))
    assert types(events)[-3:] == [T.TEXT_MESSAGE_END, T.RUN_ERROR, ] + [] or types(events)[-2:] == [T.TEXT_MESSAGE_END, T.RUN_ERROR]
    assert "model down" in events[-1].message and T.RUN_FINISHED not in types(events)


async def test_cancelling_a_run_leaves_the_agent_usable():
    gate = asyncio.Event()

    class Slow(ScriptedModel):
        async def stream(self, *a, **k):
            if self.scripts:
                yield {"messageStart": {"role": "assistant"}}
                await gate.wait()
            for e in text("back")[:0]:
                yield e

    agent = Agent(model=Slow(["x"]), callback_handler=None)
    adapter = StrandsAGUIAdapter(agent)

    async def consume():
        async for _ in adapter.run("t", "hi", None, None):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    agent.model = ScriptedModel(text("alive"))
    events = await collect(adapter, "again")
    assert body(events, T.TEXT_MESSAGE_CONTENT) == "alive"


async def test_cancelling_during_a_tool_request_answers_the_dangling_call():
    agent = make(calls(("c1", "add", ['{"a":1,"b":1}'])))
    adapter = StrandsAGUIAdapter(agent)
    agent.messages.append({"role": "assistant", "content": [{"toolUse": {"toolUseId": "c9", "name": "add", "input": {}}}]})
    adapter._repair_history()
    assert agent.messages[-1]["content"][0]["toolResult"]["toolUseId"] == "c9"


async def test_multi_turn_keeps_history_and_new_thread_starts_over():
    agent = make(text("one"), text("two"), text("fresh"))
    adapter = StrandsAGUIAdapter(agent)
    await collect(adapter, "first", "t1")
    await collect(adapter, "second", "t1")
    assert len(agent.messages) == 4
    await collect(adapter, "new chat", "t2")  # /new in Gentui
    assert len(agent.messages) == 2


# -- human approval ---------------------------------------------------------------------------


def guarded():
    DELETED.clear()
    return make(calls(("c1", "delete_file", ['{"path": "a.txt"}'])), text("ok"), tools=(delete_file,),
                hooks=[approval_hook("delete_file")])


async def test_run_pauses_before_the_protected_tool_with_an_interrupt():
    events = await collect(StrandsAGUIAdapter(guarded()))
    last = events[-1]
    assert last.type == T.RUN_FINISHED and last.outcome.type == "interrupt"
    (interrupt,) = last.outcome.interrupts
    assert interrupt.tool_call_id == "c1" and "delete_file" in interrupt.message and "a.txt" in interrupt.message
    assert T.TOOL_CALL_RESULT not in types(events) and DELETED == []


async def test_approve_runs_the_tool_and_finishes():
    adapter = StrandsAGUIAdapter(guarded())
    (interrupt,) = (await collect(adapter))[-1].outcome.interrupts
    events = await collect(adapter, "", resume=[{"interruptId": interrupt.id, "status": "resolved", "payload": {"approved": True}}])
    assert DELETED == ["a.txt"]
    assert next(e for e in events if e.type == T.TOOL_CALL_RESULT).content == "deleted a.txt"
    assert body(events, T.TEXT_MESSAGE_CONTENT) == "ok" and events[-1].outcome is None


@pytest.mark.parametrize("answer", [
    {"status": "resolved", "payload": {"approved": False}},
    {"status": "cancelled"},
    {"status": "resolved", "payload": {"something": "else"}},
])
async def test_anything_but_a_clear_yes_prevents_the_tool(answer):
    adapter = StrandsAGUIAdapter(guarded())
    (interrupt,) = (await collect(adapter))[-1].outcome.interrupts
    events = await collect(adapter, "", resume=[{"interruptId": interrupt.id, **answer}])
    assert DELETED == []
    result = next(e for e in events if e.type == T.TOOL_CALL_RESULT)
    assert result.raw_event == {"status": "error"} and "rejected" in result.content


async def test_new_text_while_an_approval_is_open_is_refused_with_an_error():
    adapter = StrandsAGUIAdapter(guarded())
    await collect(adapter)
    events = await collect(adapter, "never mind")
    assert types(events)[-1] == T.RUN_ERROR and "Approve" in events[-1].message


async def test_unprotected_tools_are_not_interrupted():
    agent = make(calls(("c1", "add", ['{"a":1,"b":2}'])), text("3"), hooks=[approval_hook("delete_file")])
    events = await collect(StrandsAGUIAdapter(agent))
    assert events[-1].outcome is None and next(e for e in events if e.type == T.TOOL_CALL_RESULT).content == "3"


# -- the real UI, end to end ------------------------------------------------------------------


async def test_ui_shows_tool_card_result_streamed_answer_and_raw_events():
    agent = make(calls(("c1", "add", ['{"a": 125, "b": 42}']), thought="multiply"), text("It is ", "167"))
    app = GentUI.from_strands(agent, splash=False, dev_pane=True).build()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press(*"add them", "enter")
        await pilot.pause(0.6)
        card = app.query_one(GenericToolWidget)
        rendered = shown(card)
        assert "add(a=125, b=42)" in rendered and "167" in rendered and "running" not in rendered
        assert [m.source for m in app.query(Markdown)] == ["It is 167"]  # once, not duplicated
        logged = "\n".join(str(line.text) for line in app.query_one("#events").lines)
        assert "strands " in logged and "TOOL_CALL_RESULT" in logged


async def test_ui_failed_tool_is_marked_failed():
    app = GentUI.from_strands(make(calls(("c1", "boom", [])), text("sorry"), tools=(boom,)), splash=False).build()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press(*"go", "enter")
        await pilot.pause(0.6)
        assert "failed" in shown(app.query_one(GenericToolWidget))


@pytest.mark.parametrize("button, deleted", [("approve", ["a.txt"]), ("reject", [])])
async def test_ui_approve_and_reject_buttons_drive_the_agent(button, deleted):
    app = GentUI.from_strands(guarded(), splash=False).build()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press(*"delete it", "enter")
        await pilot.pause(0.6)
        assert DELETED == []  # paused, nothing ran yet
        widget = app.query_one(InterruptWidget)
        await pilot.click(f"#{button}")
        await pilot.pause(0.8)
        assert DELETED == deleted
        assert "ok" in [m.source for m in app.query(Markdown)]
        assert app.query_one(InterruptWidget).query_one(f"#{button}", Button).disabled


# -- optional dependency and compatibility --------------------------------------------------------


def test_gentui_imports_and_adapts_without_strands_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "strands", None)
    monkeypatch.setitem(sys.modules, "strands.hooks", None)
    import gentui, gentui.adapters.strands  # noqa: E401  (importing must not need Strands)

    class Duck:
        name = "duck"
        messages: list = []

    assert "duck" in GentUI.from_strands(Duck()).adapter.label
    with pytest.raises(ImportError, match=r"gentui\[strands\]"):
        approval_hook("x")


def test_the_existing_clients_are_untouched():
    from gentui.tui.agui_client import AguiClient

    assert not hasattr(AguiClient, "label") and GentUI.from_strands.__self__ is GentUI


async def test_the_default_printing_handler_is_silenced_so_the_ui_is_not_scribbled_on(capsys):
    agent = Agent(model=ScriptedModel(text("quiet")))  # no callback_handler=None: Strands prints by default
    events = await collect(StrandsAGUIAdapter(agent))
    assert body(events, T.TEXT_MESSAGE_CONTENT) == "quiet" and capsys.readouterr().out == ""
