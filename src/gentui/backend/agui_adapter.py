"""Converts Strands stream events into AG-UI events (the core learning piece).

Strands `agent.stream_async()` yields plain dicts. We only care about two kinds:

  {"event": {...}}   raw model stream (Bedrock-style): text deltas, tool-use start/args/stop
  {"message": {...}} a finished message; a user message holding a `toolResult` = a tool finished

    Strands                                         AG-UI
    ---------------------------------------------   ---------------------------
    (run begins)                                    RUN_STARTED
    contentBlockDelta.delta.text                    TEXT_MESSAGE_START (once) + _CONTENT
    contentBlockStart.start.toolUse                 TOOL_CALL_START
    contentBlockDelta.delta.toolUse.input           TOOL_CALL_ARGS
    contentBlockStop                                TEXT_MESSAGE_END / TOOL_CALL_END
    message(role=user, content[toolResult])         TOOL_CALL_RESULT
    (run ends)                                      RUN_FINISHED  (or RUN_ERROR)

Events from a sub-agent arrive wrapped as {"type": "tool_stream", "tool_stream_event":
{"tool_use": <parent call>, "data": <inner event>}}. We unwrap them with a nested adapter that
forwards only the sub-agent's TOOL calls (not its chat text), so a tool the sub-agent calls
(e.g. propose_command) becomes a first-class AG-UI tool call the TUI can render.

Shared state: `run_to_agui` takes a `get_state` callable. After every tool result it compares the
state with the last one sent and emits STATE_SNAPSHOT (first time) or STATE_DELTA (JSON Patch).
"""

import copy
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import jsonpatch
from ag_ui.core import (
    BaseEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)


class StrandsToAguiAdapter:
    """Stateful translator: feed it Strands events, get AG-UI events back."""

    def __init__(self, emit_text: bool = True) -> None:
        self._emit_text = emit_text  # False for sub-agents: forward tool calls only
        self._nested: dict[str, StrandsToAguiAdapter] = {}  # one per sub-agent tool call
        self._text_id: str | None = None  # open text message, if any
        self._tool_id: str | None = None  # open tool call (args still streaming), if any

    # -- public -----------------------------------------------------------------

    def translate(self, ev: Any) -> Iterator[BaseEvent]:
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "tool_stream":
            wrapped = ev.get("tool_stream_event") or {}
            parent_id = (wrapped.get("tool_use") or {}).get("toolUseId", "")
            nested = self._nested.setdefault(parent_id, StrandsToAguiAdapter(emit_text=False))
            yield from nested.translate(wrapped.get("data"))
        elif "event" in ev:
            yield from self._model_event(ev["event"])
        elif "message" in ev:
            yield from self._message(ev["message"])

    def close(self) -> Iterator[BaseEvent]:
        """End anything still open (used when the run ends or fails mid-stream)."""
        yield from self._end_text()
        yield from self._end_tool()

    # -- raw model stream ------------------------------------------------------------

    def _model_event(self, e: dict) -> Iterator[BaseEvent]:
        if "contentBlockStart" in e:
            tool_use = e["contentBlockStart"].get("start", {}).get("toolUse")
            if tool_use:
                yield from self._end_text()
                self._tool_id = tool_use["toolUseId"]
                yield ToolCallStartEvent(
                    tool_call_id=self._tool_id,
                    tool_call_name=tool_use["name"],
                )
        elif "contentBlockDelta" in e:
            delta = e["contentBlockDelta"].get("delta", {})
            if delta.get("text"):  # AG-UI requires non-empty deltas
                if not self._emit_text:
                    return
                if self._text_id is None:
                    self._text_id = str(uuid.uuid4())
                    yield TextMessageStartEvent(message_id=self._text_id, role="assistant")
                yield TextMessageContentEvent(message_id=self._text_id, delta=delta["text"])
            elif "toolUse" in delta and self._tool_id and delta["toolUse"].get("input"):
                yield ToolCallArgsEvent(tool_call_id=self._tool_id, delta=delta["toolUse"]["input"])
        elif "contentBlockStop" in e:
            yield from self._end_text()
            yield from self._end_tool()

    def _message(self, msg: dict) -> Iterator[BaseEvent]:
        if msg.get("role") != "user":
            return
        for block in msg.get("content", []):
            result = block.get("toolResult")
            if result:
                text = "".join(c.get("text", "") for c in result.get("content", []))
                yield ToolCallResultEvent(
                    message_id=str(uuid.uuid4()),
                    tool_call_id=result["toolUseId"],
                    content=text,
                    role="tool",
                )

    # -- helpers -----------------------------------------------------------------------

    def _end_text(self) -> Iterator[BaseEvent]:
        if self._text_id:
            yield TextMessageEndEvent(message_id=self._text_id)
            self._text_id = None

    def _end_tool(self) -> Iterator[BaseEvent]:
        if self._tool_id:
            yield ToolCallEndEvent(tool_call_id=self._tool_id)
            self._tool_id = None


def _state_events(last: dict | None, current: dict) -> Iterator[BaseEvent]:
    """Snapshot the first time, JSON Patch deltas afterwards; nothing if unchanged."""
    if last is None:
        yield StateSnapshotEvent(snapshot=current)
    else:
        patch = jsonpatch.make_patch(last, current).patch
        if patch:
            yield StateDeltaEvent(delta=patch)


async def run_to_agui(
    strands_events: AsyncIterator[Any],
    thread_id: str,
    run_id: str,
    get_state: Callable[[], dict] | None = None,
    last_state: dict | None = None,
) -> AsyncIterator[BaseEvent]:
    """Wrap a whole Strands run: RUN_STARTED ... RUN_FINISHED, or RUN_ERROR on failure.

    `last_state` is what the client already has (None = send a snapshot first).
    """
    adapter = StrandsToAguiAdapter()
    last = copy.deepcopy(last_state)
    yield RunStartedEvent(thread_id=thread_id, run_id=run_id)
    try:
        if get_state:  # let the client sync its state at the start of every run
            for out in _state_events(last, current := copy.deepcopy(get_state())):
                yield out
            last = current
        async for ev in strands_events:
            for out in adapter.translate(ev):
                yield out
                if get_state and out.type == EventType.TOOL_CALL_RESULT:
                    for st in _state_events(last, current := copy.deepcopy(get_state())):
                        yield st
                    last = current
    except Exception as exc:  # noqa: BLE001 - any failure must reach the client as RUN_ERROR
        for out in adapter.close():
            yield out
        yield RunErrorEvent(message=f"{type(exc).__name__}: {exc}")
        return
    for out in adapter.close():
        yield out
    yield RunFinishedEvent(thread_id=thread_id, run_id=run_id)


__all__ = ["StrandsToAguiAdapter", "run_to_agui", "EventType"]
