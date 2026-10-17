"""Run a LangChain / LangGraph agent inside Gentui, in this process: no server, no HTTP.

`LangChainAGUIAdapter` is a Gentui client (the same `run(...)` shape as `AguiClient`). It calls
`agent.astream_events(..., version="v2")` on a compiled LangGraph graph (what `langchain.agents.create_agent`
and `langgraph.prebuilt.create_react_agent` return) and translates it into AG-UI events, which the normal
Gentui pipeline renders. Nothing here imports `langchain` unless you use `approval_middleware`.

    LangChain event (astream_events v2)                     AG-UI
    ------------------------------------------------------  ----------------------------------
    (invocation starts)                                     RUN_STARTED
    on_chat_model_stream  chunk.content text                TEXT_MESSAGE_START (once) + _CONTENT
    on_chat_model_stream  thinking / reasoning_content      REASONING_START + REASONING_MESSAGE_*
    on_chat_model_stream  chunk.tool_call_chunks            TOOL_CALL_START + TOOL_CALL_ARGS
    on_chat_model_end                                       TEXT_MESSAGE_END / REASONING_*_END / TOOL_CALL_END
    on_tool_end           ToolMessage                       TOOL_CALL_RESULT (raw_event carries the status)
    (graph paused by interrupt())                           RUN_FINISHED with an interrupt outcome
    (invocation ends)                                       RUN_FINISHED
    (exception)                                             RUN_ERROR

Conversation memory is LangGraph's checkpointer, keyed by Gentui's thread id (so /new starts a fresh chat). If the
graph has none, the adapter gives it an in-memory one. Human approval uses LangGraph's `interrupt()`:
`approval_middleware` pauses a tool, the adapter turns the pause into an AG-UI interrupt, Gentui shows Approve /
Reject, and the answer resumes the graph with `Command(resume=...)`.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from ag_ui.core import (
    BaseEvent,
    Interrupt,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

APPROVAL_SCHEMA = {
    "type": "object",
    "properties": {"approved": {"type": "boolean"}},
    "required": ["approved"],
}


def approval_middleware(*tool_names: str, message: str | Callable[[str, dict[str, Any]], str] | None = None) -> Any:
    """A LangChain agent middleware that makes the named tools (all tools if none are named) wait for approval.

        agent = create_agent(model, tools, middleware=[approval_middleware("delete_file")])

    Before the tool runs the graph pauses; Gentui shows Approve / Reject. Approve runs the tool. Reject skips it:
    the model is told "rejected by the user" as the tool's result and carries on. `message` is the question shown
    to the user (a string, or a function of the tool name and input).
    """
    try:
        from langchain.agents.middleware import AgentMiddleware
        from langchain_core.messages import ToolMessage
        from langgraph.types import interrupt
    except ImportError as exc:
        raise ImportError(
            "approval_middleware needs LangChain. Install it with: pip install 'gentui[langchain]'"
        ) from exc
    names = set(tool_names)

    def ask(request: Any) -> ToolMessage | None:
        """None means go ahead and run the tool; otherwise the message that stands in for its result."""
        call = request.tool_call
        name, tool_input = call["name"], call.get("args") or {}
        if names and name not in names:
            return None
        if callable(message):
            question = message(name, tool_input)
        else:
            args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False, default=str)}" for k, v in tool_input.items())
            question = message or f"Allow {name}({args})?"
        response = interrupt({"message": question, "tool": name, "input": tool_input, "tool_call_id": call["id"]})
        if isinstance(response, dict) and response.get("approved") is True:
            return None
        return ToolMessage(
            content=f"The user rejected running {name}.", tool_call_id=call["id"], name=name, status="error"
        )

    class ApprovalMiddleware(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            return ask(request) or handler(request)

        async def awrap_tool_call(self, request, handler):
            return ask(request) or await handler(request)

    return ApprovalMiddleware()


class LangChainAGUIAdapter:
    """Gentui client for a compiled LangGraph graph / LangChain agent. Memory lives in its checkpointer."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        if getattr(agent, "checkpointer", None) is None:
            # without a checkpointer the graph forgets every turn and cannot pause for approval
            from langgraph.checkpoint.memory import InMemorySaver

            agent.checkpointer = InMemorySaver()
        name = getattr(agent, "name", None)
        self.label = f"LangChain agent{f' {name!r}' if name and name != 'LangGraph' else ''} (in-process, no server)"
        self.on_raw: Callable[[str], None] | None = None  # the dev pane: LangChain events in, AG-UI events out

    async def run(
        self,
        thread_id: str,
        text: str,
        forwarded_props: dict[str, Any] | None = None,
        resume: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        """One user message (or, with `resume`, the answers to open interrupts) -> AG-UI events."""
        run_id = str(uuid.uuid4())
        translator = LangChainTranslator()
        config = {"configurable": {"thread_id": thread_id}}
        stream = None
        yield self._out(RunStartedEvent(thread_id=thread_id, run_id=run_id))
        try:
            payload = await self._input(config, text, resume)
            stream = self.agent.astream_events(payload, config, version="v2")
            async for ev in stream:
                self._log_raw(ev)
                for out in translator.translate(ev):
                    yield self._out(out)
            for out in translator.close():
                yield self._out(out)
            state = await self.agent.aget_state(config)
            yield self._out(translator.finished(thread_id, run_id, list(state.interrupts or ())))
        except asyncio.CancelledError:  # the user stopped the run (/new, quit): leave the thread reusable
            await self._repair_history(config)
            raise
        except Exception as exc:  # noqa: BLE001 - every failure must reach the UI as RUN_ERROR
            for out in translator.close():
                yield self._out(out)
            yield self._out(RunErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if stream is not None:
                await stream.aclose()

    # -- conversation state ---------------------------------------------------------------

    async def _input(self, config: dict, text: str, resume: list[dict[str, Any]] | None) -> Any:
        if resume:
            from langgraph.types import Command

            return Command(resume=self._resume_answers(resume))
        if (await self.agent.aget_state(config)).interrupts:
            raise RuntimeError("the agent is waiting for your Approve / Reject before it can take a new message")
        return {"messages": [{"role": "user", "content": text}]}

    @staticmethod
    def _resume_answers(resume: list[dict[str, Any]]) -> dict[str, Any]:
        """AG-UI resume entries -> {interrupt id: answer}. The answer is a dict like {"approved": true}."""
        answers = {}
        for entry in resume:
            if entry.get("status") == "resolved" and isinstance(entry.get("payload"), dict):
                answers[entry["interruptId"]] = entry["payload"]
            else:  # cancelled, or an answer we cannot read: never treat it as consent
                answers[entry["interruptId"]] = {"approved": False, "cancelled": True}
        return answers

    async def _repair_history(self, config: dict) -> None:
        """A run stopped between a tool request and its result leaves a history providers reject. Answer the
        dangling tool calls with an error result."""
        try:
            state = await self.agent.aget_state(config)
            messages = (state.values or {}).get("messages") or []
            if state.interrupts or not messages or getattr(messages[-1], "type", None) != "ai":
                return
            calls = getattr(messages[-1], "tool_calls", None) or []
            if calls:
                from langchain_core.messages import ToolMessage

                await self.agent.aupdate_state(config, {"messages": [
                    ToolMessage(content="Cancelled by the user.", tool_call_id=c["id"], name=c["name"], status="error")
                    for c in calls
                ]})
        except Exception:  # noqa: BLE001 - best effort while being cancelled
            pass

    # -- dev pane ---------------------------------------------------------------------------

    def _log_raw(self, ev: Any) -> None:
        if self.on_raw and isinstance(ev, dict) and ev.get("event") in _RAW_EVENTS:
            shown = {"event": ev["event"], "name": ev.get("name"), "data": ev.get("data")}
            self.on_raw("langchain " + json.dumps(shown, default=_brief))

    def _out(self, ev: BaseEvent) -> BaseEvent:
        if self.on_raw:
            self.on_raw(ev.model_dump_json(by_alias=True, exclude_none=True))
        return ev


# the LangChain events shown in the dev pane; the rest (chain/graph bookkeeping) is noise
_RAW_EVENTS = ("on_chat_model_stream", "on_chat_model_end", "on_tool_start", "on_tool_end", "on_tool_error")


def _brief(obj: Any) -> Any:
    """json default: LangChain messages as their content (+ tool calls), anything else as text."""
    content = getattr(obj, "content", None)
    if content is not None:
        return {"content": content, "tool_calls": getattr(obj, "tool_calls", None) or None}
    return str(obj)


class LangChainTranslator:
    """Stateful: feed it the astream_events of one invocation, get AG-UI events back."""

    def __init__(self) -> None:
        self._text_id: str | None = None
        self._reasoning_id: str | None = None
        self._open_calls: dict[Any, str] = {}  # chunk index -> tool call id, for calls still streaming arguments
        self._started: set[str] = set()  # every tool call id announced so far
        self._resulted: set[str] = set()  # tool call ids whose result was already sent
        self._streamed = False  # did this model call stream anything? if not, on_chat_model_end fills in

    def translate(self, ev: Any) -> Iterator[BaseEvent]:
        if not isinstance(ev, dict):
            return
        kind, data = ev.get("event"), ev.get("data") or {}
        if kind == "on_chat_model_stream":
            yield from self._chunk(data.get("chunk"))
        elif kind == "on_chat_model_end":
            yield from self._model_end(data.get("output"))
        elif kind == "on_tool_end":
            yield from self._tool_result(data.get("output"))
        elif kind == "on_chain_end":
            # a tool that never ran (rejected by a middleware) has no on_tool_end; its stand-in result only
            # shows up in what the tools node returns
            output = data.get("output")
            update = output.get("messages") if isinstance(output, dict) else getattr(output, "update", None)
            if isinstance(update, dict):
                update = update.get("messages")
            for message in update if isinstance(update, list) else []:
                yield from self._tool_result(message)

    def close(self) -> Iterator[BaseEvent]:
        """End whatever is still open (the stream ended early or failed)."""
        yield from self._end_reasoning()
        yield from self._end_text()
        yield from self._end_calls()

    def finished(self, thread_id: str, run_id: str, pending: list[Any]) -> RunFinishedEvent:
        """RUN_FINISHED: with an interrupt outcome when the graph paused for a decision."""
        if not pending:
            return RunFinishedEvent(thread_id=thread_id, run_id=run_id)
        interrupts = []
        for native in pending:
            value = native.value
            info = value if isinstance(value, dict) else {}
            question = info.get("message") or (value if isinstance(value, str) else None)
            call_id = info.get("tool_call_id")
            interrupts.append(Interrupt(
                id=native.id,
                reason="tool_call" if call_id else "input_required",
                message=str(question) if question else "The agent is waiting for you",
                tool_call_id=call_id,
                response_schema=APPROVAL_SCHEMA,
            ))
        return RunFinishedEvent(thread_id=thread_id, run_id=run_id, outcome=RunFinishedInterruptOutcome(interrupts=interrupts))

    # -- the model stream ----------------------------------------------------------------------

    def _chunk(self, chunk: Any) -> Iterator[BaseEvent]:
        if chunk is None:
            return
        content = getattr(chunk, "content", "")
        blocks = [content] if isinstance(content, str) else (content if isinstance(content, list) else [])
        thought = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content") or ""
        words = ""
        for block in blocks:
            if isinstance(block, str):
                words += block
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    words += block.get("text") or ""
                elif block.get("type") in ("thinking", "reasoning"):
                    thought += block.get("thinking") or block.get("reasoning") or block.get("text") or ""
        if thought:
            self._streamed = True
            yield from self._reasoning(thought)
        if words:  # AG-UI requires non-empty deltas
            self._streamed = True
            yield from self._text(words)
        for part in getattr(chunk, "tool_call_chunks", None) or []:
            self._streamed = True
            yield from self._call_chunk(part)

    def _call_chunk(self, part: dict) -> Iterator[BaseEvent]:
        index = part.get("index") if part.get("index") is not None else part.get("id")
        if part.get("id") and part.get("name") and part["id"] not in self._started:
            yield from self._end_reasoning()
            yield from self._end_text()
            if index in self._open_calls:  # a new call reusing an index: the old one is complete
                yield ToolCallEndEvent(tool_call_id=self._open_calls.pop(index))
            self._open_calls[index] = part["id"]
            self._started.add(part["id"])
            yield ToolCallStartEvent(tool_call_id=part["id"], tool_call_name=part["name"])
        call_id = self._open_calls.get(index)
        if call_id and part.get("args"):
            yield ToolCallArgsEvent(tool_call_id=call_id, delta=part["args"])

    def _model_end(self, output: Any) -> Iterator[BaseEvent]:
        """One model call is over. Close its blocks, and fill in what a non-streaming model never streamed."""
        if not self._streamed and output is not None:
            yield from self._chunk(output)
            for call in getattr(output, "tool_calls", None) or []:
                if call.get("id") and call["id"] not in self._started:
                    yield from self._call_chunk({
                        "id": call["id"], "name": call["name"], "index": call["id"],
                        "args": json.dumps(call.get("args") or {}, ensure_ascii=False, default=str),
                    })
        self._streamed = False
        yield from self.close()

    def _tool_result(self, output: Any) -> Iterator[BaseEvent]:
        call_id = getattr(output, "tool_call_id", None)
        if call_id and call_id not in self._resulted:  # a Command (or anything else) is not a result Gentui can show
            self._resulted.add(call_id)
            yield ToolCallResultEvent(
                message_id=str(uuid.uuid4()),
                tool_call_id=call_id,
                content=_content_text(getattr(output, "content", "")),
                role="tool",
                raw_event={"status": getattr(output, "status", None) or "success"},
            )

    # -- open blocks ---------------------------------------------------------------------------

    def _reasoning(self, delta: str) -> Iterator[BaseEvent]:
        if self._reasoning_id is None:
            yield from self._end_text()
            self._reasoning_id = str(uuid.uuid4())
            yield ReasoningStartEvent(message_id=self._reasoning_id)
            yield ReasoningMessageStartEvent(message_id=self._reasoning_id, role="reasoning")
        yield ReasoningMessageContentEvent(message_id=self._reasoning_id, delta=delta)

    def _text(self, delta: str) -> Iterator[BaseEvent]:
        yield from self._end_reasoning()
        if self._text_id is None:
            self._text_id = str(uuid.uuid4())
            yield TextMessageStartEvent(message_id=self._text_id, role="assistant")
        yield TextMessageContentEvent(message_id=self._text_id, delta=delta)

    def _end_reasoning(self) -> Iterator[BaseEvent]:
        if self._reasoning_id:
            yield ReasoningMessageEndEvent(message_id=self._reasoning_id)
            yield ReasoningEndEvent(message_id=self._reasoning_id)
            self._reasoning_id = None

    def _end_text(self) -> Iterator[BaseEvent]:
        if self._text_id:
            yield TextMessageEndEvent(message_id=self._text_id)
            self._text_id = None

    def _end_calls(self) -> Iterator[BaseEvent]:
        for call_id in self._open_calls.values():
            yield ToolCallEndEvent(tool_call_id=call_id)
        self._open_calls.clear()


def _content_text(content: Any) -> str:
    """A LangChain tool result's content is a string or a list of blocks; Gentui's TOOL_CALL_RESULT is one string."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else [content]:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, dict):  # image, file, ...: say what it is rather than pretend it is text
            parts.append(f"[{block.get('type', 'content')}]")
        else:
            parts.append(json.dumps(block, ensure_ascii=False, default=str))
    return "\n".join(parts)
