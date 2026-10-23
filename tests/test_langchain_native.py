"""The in-process LangChain adapter: a real LangChain agent driven by a scripted chat model (no network)."""

import pytest
from ag_ui.core import EventType as T

from gentui.adapters.langchain import LangChainAGUIAdapter, approval_middleware

pytest.importorskip("langchain")
from langchain.agents import create_agent  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from langchain_core.outputs import ChatGenerationChunk, ChatResult, ChatGeneration  # noqa: E402
from langchain_core.tools import tool  # noqa: E402


class ScriptedModel(BaseChatModel):
    """Each call to the model plays the next script: a list of AIMessageChunk."""

    scripts: list = []

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        chunks = self.scripts.pop(0)
        message = chunks[0]
        for c in chunks[1:]:
            message = message + c
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=message.content, tool_calls=message.tool_calls))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for c in self.scripts.pop(0):
            yield ChatGenerationChunk(message=c)


def text(*parts):
    return [AIMessageChunk(content=p) for p in parts]


def call(call_id, name, *args, index=0):
    first = AIMessageChunk(content="", tool_call_chunks=[{"id": call_id, "name": name, "args": args[0], "index": index}])
    return [first] + [AIMessageChunk(content="", tool_call_chunks=[{"id": None, "name": None, "args": a, "index": index}]) for a in args[1:]]


DELETED: list[str] = []


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def delete_file(path: str) -> str:
    """Delete a file."""
    DELETED.append(path)
    return f"deleted {path}"


def make(*scripts, tools=(add,), middleware=()):
    return create_agent(ScriptedModel(scripts=list(scripts)), list(tools), middleware=list(middleware))


async def collect(adapter, text="hi", thread="t", resume=None):
    return [ev async for ev in adapter.run(thread, text, None, resume)]


def types(events):
    return [e.type for e in events]


def body(events, kind):
    return "".join(e.delta for e in events if e.type == kind)


async def test_text_streams_once_with_stable_ids():
    events = await collect(LangChainAGUIAdapter(make(text("Hel", "lo ", "there"))))
    assert types(events) == [T.RUN_STARTED, T.TEXT_MESSAGE_START, *[T.TEXT_MESSAGE_CONTENT] * 3, T.TEXT_MESSAGE_END, T.RUN_FINISHED]
    assert body(events, T.TEXT_MESSAGE_CONTENT) == "Hello there"
    assert len({getattr(e, "message_id", None) for e in events[1:-1]}) == 1


async def test_tool_lifecycle_args_result_and_following_answer():
    agent = make(call("c1", "add", '{"a": ', "2, ", '"b": 3}'), text("It is 5"))
    events = await collect(LangChainAGUIAdapter(agent))
    assert types(events) == [
        T.RUN_STARTED, T.TOOL_CALL_START, T.TOOL_CALL_ARGS, T.TOOL_CALL_ARGS, T.TOOL_CALL_ARGS, T.TOOL_CALL_END,
        T.TOOL_CALL_RESULT, T.TEXT_MESSAGE_START, T.TEXT_MESSAGE_CONTENT, T.TEXT_MESSAGE_END, T.RUN_FINISHED,
    ]
    assert events[1].tool_call_name == "add" and events[1].tool_call_id == "c1"
    assert body(events, T.TOOL_CALL_ARGS) == '{"a": 2, "b": 3}'
    result = next(e for e in events if e.type == T.TOOL_CALL_RESULT)
    assert (result.tool_call_id, result.content, result.raw_event) == ("c1", "5", {"status": "success"})


async def test_reasoning_comes_before_the_answer():
    thought = [AIMessageChunk(content=[{"type": "thinking", "thinking": "hmm"}])]
    events = await collect(LangChainAGUIAdapter(make(thought + text("ok"))))
    assert types(events) == [
        T.RUN_STARTED, T.REASONING_START, T.REASONING_MESSAGE_START, T.REASONING_MESSAGE_CONTENT,
        T.REASONING_MESSAGE_END, T.REASONING_END, T.TEXT_MESSAGE_START, T.TEXT_MESSAGE_CONTENT,
        T.TEXT_MESSAGE_END, T.RUN_FINISHED,
    ]


async def test_reasoning_content_from_additional_kwargs_is_shown():
    """What langchain-ollama (reasoning=True) and other providers send: the thought next to an empty content."""
    thought = [AIMessageChunk(content="", additional_kwargs={"reasoning_content": "hm"}),
               AIMessageChunk(content="", additional_kwargs={"reasoning_content": "mm"})]
    events = await collect(LangChainAGUIAdapter(make(thought + text("ok"))))
    assert body(events, T.REASONING_MESSAGE_CONTENT) == "hmmm" and body(events, T.TEXT_MESSAGE_CONTENT) == "ok"
    assert types(events).index(T.REASONING_END) < types(events).index(T.TEXT_MESSAGE_START)


async def test_conversation_is_kept_per_thread():
    agent = make(text("one"), text("two"))
    adapter = LangChainAGUIAdapter(agent)
    await collect(adapter, thread="a")
    await collect(adapter, thread="a")
    assert len(agent.get_state({"configurable": {"thread_id": "a"}}).values["messages"]) == 4
    assert agent.get_state({"configurable": {"thread_id": "b"}}).values == {}


async def test_model_failure_becomes_run_error():
    events = await collect(LangChainAGUIAdapter(make()))  # no script left: the model raises
    assert events[-1].type == T.RUN_ERROR and events[0].type == T.RUN_STARTED


async def test_approval_pauses_then_approve_runs_the_tool():
    DELETED.clear()
    agent = make(call("c1", "delete_file", '{"path": "a.txt"}'), text("gone"), tools=(delete_file,),
                 middleware=[approval_middleware("delete_file")])
    adapter = LangChainAGUIAdapter(agent)
    paused = await collect(adapter)
    interrupt = paused[-1].outcome.interrupts[0]
    assert paused[-1].type == T.RUN_FINISHED and interrupt.tool_call_id == "c1" and "delete_file" in interrupt.message
    assert DELETED == []
    done = await collect(adapter, resume=[{"interruptId": interrupt.id, "status": "resolved", "payload": {"approved": True}}])
    assert DELETED == ["a.txt"] and body(done, T.TEXT_MESSAGE_CONTENT) == "gone"
    assert done[-1].outcome is None


async def test_reject_and_cancel_never_run_the_tool():
    for entry in ({"status": "resolved", "payload": {"approved": False}}, {"status": "cancelled"}):
        DELETED.clear()
        agent = make(call("c1", "delete_file", '{"path": "a.txt"}'), text("ok, not deleted"), tools=(delete_file,),
                     middleware=[approval_middleware()])
        adapter = LangChainAGUIAdapter(agent)
        paused = await collect(adapter)
        done = await collect(adapter, resume=[{"interruptId": paused[-1].outcome.interrupts[0].id, **entry}])
        assert DELETED == []
        result = next(e for e in done if e.type == T.TOOL_CALL_RESULT)
        assert result.raw_event == {"status": "error"} and "rejected" in result.content


async def test_new_message_while_waiting_is_an_error():
    agent = make(call("c1", "delete_file", '{"path": "a"}'), tools=(delete_file,), middleware=[approval_middleware()])
    adapter = LangChainAGUIAdapter(agent)
    await collect(adapter)
    assert (await collect(adapter, "again"))[-1].type == T.RUN_ERROR
