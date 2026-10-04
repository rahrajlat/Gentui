"""Adapter test using Strands event shapes captured from a real run (no LLM needed)."""

import pytest

from gentui.backend.agui_adapter import run_to_agui

TOOL_ID = "tooluse_1"

FAKE_RUN = [
    {"init_event_loop": True},
    {"event": {"messageStart": {"role": "assistant"}}},
    {"event": {"contentBlockStart": {"start": {}}}},
    {"event": {"contentBlockDelta": {"delta": {"text": ""}}}},  # empty: must be skipped
    {"event": {"contentBlockStop": {}}},
    {"event": {"contentBlockStart": {"start": {"toolUse": {"name": "shell_agent", "toolUseId": TOOL_ID}}}}},
    {"event": {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"input": "du -sh ."}'}}}}},
    {"event": {"contentBlockStop": {}}},
    {"type": "tool_stream", "tool_stream_event": {}},  # nested sub-agent noise: ignored
    {"message": {"role": "user", "content": [{"toolResult": {"toolUseId": TOOL_ID, "content": [{"text": "ok"}]}}]}},
    {"event": {"contentBlockDelta": {"delta": {"text": "Here"}}}},
    {"event": {"contentBlockDelta": {"delta": {"text": " you go"}}}},
    {"event": {"contentBlockStop": {}}},
]


async def _stream(events, fail=False):
    for e in events:
        yield e
    if fail:
        raise RuntimeError("boom")


async def _collect(events, fail=False):
    return [e async for e in run_to_agui(_stream(events, fail), "t1", "r1")]


@pytest.mark.asyncio
async def test_full_run_event_order():
    out = await _collect(FAKE_RUN)
    types = [e.type.value for e in out]
    assert types == [
        "RUN_STARTED",
        "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert out[1].tool_call_name == "shell_agent"
    assert out[2].delta == '{"input": "du -sh ."}'
    assert out[4].content == "ok" and out[4].tool_call_id == TOOL_ID


@pytest.mark.asyncio
async def test_error_closes_open_text_and_emits_run_error():
    events = [{"event": {"contentBlockDelta": {"delta": {"text": "hi"}}}}]
    types = [e.type.value for e in await _collect(events, fail=True)]
    assert types == ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_ERROR"]


def _wrap(inner, parent="tooluse_parent"):
    return {"type": "tool_stream", "tool_stream_event": {"tool_use": {"toolUseId": parent}, "data": inner}}


@pytest.mark.asyncio
async def test_sub_agent_tool_calls_are_unwrapped_but_its_text_is_not():
    events = [
        _wrap({"event": {"contentBlockDelta": {"delta": {"text": "sub-agent chatter"}}}}),
        _wrap({"event": {"contentBlockStart": {"start": {"toolUse": {"name": "propose_command", "toolUseId": "inner1"}}}}}),
        _wrap({"event": {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"command": "ls"}'}}}}}),
        _wrap({"event": {"contentBlockStop": {}}}),
    ]
    out = await _collect(events)
    assert [e.type.value for e in out] == ["RUN_STARTED", "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "RUN_FINISHED"]
    assert out[1].tool_call_name == "propose_command" and out[1].tool_call_id == "inner1"


@pytest.mark.asyncio
async def test_state_snapshot_then_delta_after_tool_result():
    state = {"plan": []}

    def get_state():
        return state

    async def events():
        yield {"message": {"role": "user", "content": [{"toolResult": {"toolUseId": "t", "content": [{"text": "ok"}]}}]}}

    out = []
    async for e in run_to_agui(events(), "t1", "r1", get_state=get_state):
        out.append(e)
        if e.type.value == "STATE_SNAPSHOT":
            state["plan"] = [{"content": "a", "status": "pending"}]  # the tool changes state

    types = [e.type.value for e in out]
    assert types == ["RUN_STARTED", "STATE_SNAPSHOT", "TOOL_CALL_RESULT", "STATE_DELTA", "RUN_FINISHED"]
    assert out[3].delta[0].op == "add" and out[3].delta[0].path == "/plan/0"  # RFC 6902 patch
