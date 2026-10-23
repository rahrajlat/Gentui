"""Run a Strands agent inside Gentui, in this process: no server, no HTTP.

`StrandsAGUIAdapter` is a Gentui client (the same `run(...)` shape as `AguiClient`). It calls
`agent.stream_async()` and translates the Strands stream into AG-UI events, which the normal Gentui
pipeline renders. Nothing here imports `strands` unless you use `approval_hook`, so Gentui works without it.

    Strands stream (dicts from stream_async)                AG-UI
    ------------------------------------------------------  ----------------------------------
    (invocation starts)                                     RUN_STARTED
    {"event": contentBlockDelta.delta.text}                 TEXT_MESSAGE_START (once) + _CONTENT
    {"event": contentBlockDelta.delta.reasoningContent}     REASONING_START + REASONING_MESSAGE_*
    {"event": contentBlockStart.start.toolUse}              TOOL_CALL_START
    {"event": contentBlockDelta.delta.toolUse.input}        TOOL_CALL_ARGS
    {"event": contentBlockStop}                             TEXT_MESSAGE_END / REASONING_*_END / TOOL_CALL_END
    {"message": role=user, content[toolResult]}             TOOL_CALL_RESULT (raw_event carries Strands' status)
    {"result": stop_reason="interrupt"}                     RUN_FINISHED with an interrupt outcome
    (invocation ends)                                       RUN_FINISHED
    (exception)                                             RUN_ERROR

Only the raw `event` stream is used for text, reasoning and tool arguments. Strands also yields convenience
events (`data`, `reasoningText`, `current_tool_use`) carrying the same content; ignoring them is what prevents
duplicated text. The raw stream carries true deltas, so no delta arithmetic is needed.

Human approval uses Strands interrupts: `approval_hook` pauses a tool in `BeforeToolCallEvent`, the adapter turns
the pause into an AG-UI interrupt, Gentui shows Approve / Reject, and the answer resumes the agent.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
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

APPROVAL_INTERRUPT = "gentui_approval"
APPROVAL_SCHEMA = {
    "type": "object",
    "properties": {"approved": {"type": "boolean"}},
    "required": ["approved"],
}

# the Strands events shown in the dev pane; the rest are bookkeeping or duplicates of these
_RAW_KEYS = ("event", "message", "tool_stream_event", "tool_interrupt_event", "tool_cancel_event", "force_stop")


_OLLAMA_REASONING: type | None = None


def ollama_model(model_id: str, *, think: bool | str | None = True, host: str | None = None, **config: Any) -> Any:
    """A Strands `OllamaModel` that streams the model's thinking, so Gentui can show it.

        agent = Agent(model=ollama_model("gpt-oss:20b"), tools=[...])
        agent = create_harness(model=ollama_model("gpt-oss:120b-cloud"), ...)     # also takes this

    Strands' own `OllamaModel` (and so `model="ollama/..."` in the harness) discards the `thinking` that Ollama streams,
    so a reasoning model shows no thoughts at all. This one forwards them as reasoning blocks. `think` is passed to Ollama
    (`True`, or a level such as "low" / "medium" / "high" for gpt-oss; `None` leaves it to the model). Models that cannot
    think need `think=None`. `host` defaults to `OLLAMA_HOST`, and `OLLAMA_API_KEY` is sent as a bearer token. Other
    keyword arguments are Strands' OllamaModel config (`temperature`, `max_tokens`, ...).
    """
    global _OLLAMA_REASONING
    try:
        import ollama
        from strands.models.ollama import OllamaModel
    except ImportError as exc:
        raise ImportError(
            "ollama_model needs Strands with Ollama. Install it with: pip install 'gentui[strands,ollama]'"
        ) from exc

    if _OLLAMA_REASONING is None:

        class OllamaReasoningModel(OllamaModel):
            think: bool | str | None = True

            def _format_request_message_contents(self, role, content):
                if "reasoningContent" in content:  # Ollama has no place for earlier thoughts: drop them from the history
                    return []
                return super()._format_request_message_contents(role, content)

            def format_request(self, messages, tool_specs=None, system_prompt=None):
                request = super().format_request(messages, tool_specs, system_prompt)
                if self.think is not None:
                    request.setdefault("think", self.think)
                return request

            async def stream(self, messages, tool_specs=None, system_prompt=None, *, tool_choice=None, **kwargs):
                request = self.format_request(messages, tool_specs, system_prompt)
                client = ollama.AsyncClient(self.host, **self.client_args)
                block: str | None = None  # the open block: "thinking" or "text"
                tool_requested, event = False, None
                try:
                    response = await client.chat(**request)
                    yield self.format_chunk({"chunk_type": "message_start"})
                    async for event in response:
                        message = event.message
                        if message.thinking:
                            if block != "thinking":
                                if block:
                                    yield self.format_chunk({"chunk_type": "content_stop", "data_type": block})
                                block = "thinking"
                            yield {"contentBlockDelta": {"delta": {"reasoningContent": {"text": message.thinking}}}}
                        if message.content:
                            if block != "text":
                                if block:
                                    yield {"contentBlockStop": {}}
                                block = "text"
                                yield self.format_chunk({"chunk_type": "content_start", "data_type": "text"})
                            yield self.format_chunk({"chunk_type": "content_delta", "data_type": "text", "data": message.content})
                        for call in message.tool_calls or []:
                            if block:
                                yield {"contentBlockStop": {}}
                                block = None
                            yield self.format_chunk({"chunk_type": "content_start", "data_type": "tool", "data": call})
                            yield self.format_chunk({"chunk_type": "content_delta", "data_type": "tool", "data": call})
                            yield self.format_chunk({"chunk_type": "content_stop", "data_type": "tool", "data": call})
                            tool_requested = True
                except ollama.ResponseError as error:
                    if any(m in str(error).lower() for m in self.OVERFLOW_MESSAGES):
                        from strands.types.exceptions import ContextWindowOverflowException

                        raise ContextWindowOverflowException(str(error)) from error
                    raise
                if block:
                    yield {"contentBlockStop": {}}
                reason = "tool_use" if tool_requested else (event.done_reason if event else None)
                yield self.format_chunk({"chunk_type": "message_stop", "data": reason})
                if event is not None:
                    yield self.format_chunk({"chunk_type": "metadata", "data": event})

        _OLLAMA_REASONING = OllamaReasoningModel

    api_key = os.environ.get("OLLAMA_API_KEY")
    model = _OLLAMA_REASONING(
        host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        ollama_client_args={"headers": {"Authorization": f"Bearer {api_key}"}} if api_key else None,
        model_id=model_id,
        **config,
    )
    model.think = think
    return model


def approval_hook(*tool_names: str, message: str | Callable[[str, dict[str, Any]], str] | None = None) -> Callable:
    """A Strands hook that makes the named tools (all tools if none are named) wait for the user's approval.

        agent.add_hook(approval_hook("delete_file"))     # or Agent(hooks=[approval_hook("delete_file")])

    Before the tool runs the agent pauses; Gentui shows Approve / Reject. Approve runs the tool. Reject cancels
    it: the model is told "rejected by the user" as the tool's result and carries on. `message` is the question
    shown to the user (a string, or a function of the tool name and input).
    """
    try:
        from strands.hooks import BeforeToolCallEvent
    except ImportError as exc:
        raise ImportError(
            "approval_hook needs Strands Agents. Install it with: pip install 'gentui[strands]'"
        ) from exc
    names = set(tool_names)

    def hook(event: BeforeToolCallEvent) -> None:
        name, tool_input = event.tool_use["name"], event.tool_use.get("input") or {}
        if names and name not in names:
            return
        if callable(message):
            question = message(name, tool_input)
        else:
            args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False, default=str)}" for k, v in tool_input.items())
            question = message or f"Allow {name}({args})?"
        response = event.interrupt(APPROVAL_INTERRUPT, reason={"message": question, "tool": name, "input": tool_input})
        if not (isinstance(response, dict) and response.get("approved") is True):
            event.cancel_tool = f"The user rejected running {name}."

    return hook


class StrandsAGUIAdapter:
    """Gentui client for an instantiated Strands `Agent`. Keeps the agent's own conversation across turns."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        if type(getattr(agent, "callback_handler", None)).__name__ == "PrintingCallbackHandler":
            # Strands' default handler prints the reply to stdout, which would scribble over the terminal UI
            agent.callback_handler = lambda **kwargs: None
        name = getattr(agent, "name", None)
        self.label = f"Strands agent{f' {name!r}' if name else ''} (in-process, no server)"
        self.on_raw: Callable[[str], None] | None = None  # the dev pane: Strands events in, AG-UI events out
        self._thread_id: str | None = None

    async def run(
        self,
        thread_id: str,
        text: str,
        forwarded_props: dict[str, Any] | None = None,
        resume: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        """One user message (or, with `resume`, the answers to open interrupts) -> AG-UI events."""
        run_id = str(uuid.uuid4())
        translator = StrandsTranslator()
        stream = None
        yield self._out(RunStartedEvent(thread_id=thread_id, run_id=run_id))
        try:
            self._follow_thread(thread_id)
            prompt = self._resume_prompt(resume) if resume else self._text_prompt(text)
            stream = self.agent.stream_async(prompt)
            async for ev in stream:
                self._log_raw(ev)
                for out in translator.translate(ev):
                    yield self._out(out)
            for out in translator.close():
                yield self._out(out)
            yield self._out(translator.finished(thread_id, run_id))
        except asyncio.CancelledError:  # the user stopped the run (/new, quit): leave the agent reusable
            self._repair_history()
            raise
        except Exception as exc:  # noqa: BLE001 - every failure must reach the UI as RUN_ERROR
            for out in translator.close():
                yield self._out(out)
            yield self._out(RunErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if stream is not None:
                await stream.aclose()

    # -- conversation state ---------------------------------------------------------------

    def _follow_thread(self, thread_id: str) -> None:
        """Gentui's /new makes a new thread id: start the agent over, like a new chat. The first thread adopts
        whatever history the agent was created with."""
        if self._thread_id is not None and thread_id != self._thread_id:
            self.agent.messages.clear()
            state = getattr(self.agent, "_interrupt_state", None)
            if state is not None:
                state.deactivate()
        self._thread_id = thread_id

    def _text_prompt(self, text: str) -> str:
        state = getattr(self.agent, "_interrupt_state", None)
        if state is not None and state.activated:
            raise RuntimeError("the agent is waiting for your Approve / Reject before it can take a new message")
        return text

    @staticmethod
    def _resume_prompt(resume: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """AG-UI resume entries -> Strands interrupt responses. The answer is a dict like {"approved": true}."""
        prompt = []
        for entry in resume:
            if entry.get("status") == "resolved" and isinstance(entry.get("payload"), dict):
                response = entry["payload"]
            else:  # cancelled, or an answer we cannot read: never treat it as consent
                response = {"approved": False, "cancelled": True}
            prompt.append({"interruptResponse": {"interruptId": entry["interruptId"], "response": response}})
        return prompt

    def _repair_history(self) -> None:
        """A run stopped between a tool request and its result leaves a history providers reject. Answer the
        dangling tool calls with an error result."""
        messages = self.agent.messages
        if not messages or messages[-1].get("role") != "assistant":
            return
        calls = [b["toolUse"]["toolUseId"] for b in messages[-1].get("content", []) if "toolUse" in b]
        if calls:
            messages.append({"role": "user", "content": [
                {"toolResult": {"toolUseId": i, "status": "error", "content": [{"text": "Cancelled by the user."}]}}
                for i in calls
            ]})

    # -- dev pane ---------------------------------------------------------------------------

    def _log_raw(self, ev: Any) -> None:
        if self.on_raw and isinstance(ev, dict):
            shown = {k: ev[k] for k in _RAW_KEYS if k in ev}
            if shown:
                self.on_raw("strands " + json.dumps(shown, default=str))

    def _out(self, ev: BaseEvent) -> BaseEvent:
        if self.on_raw:
            self.on_raw(ev.model_dump_json(by_alias=True, exclude_none=True))
        return ev


class StrandsTranslator:
    """Stateful: feed it the Strands events of one invocation, get AG-UI events back."""

    def __init__(self, nested: bool = False) -> None:
        self._nested = nested  # a sub-agent's stream: forward its tool calls, keep its chat and thoughts hidden
        self._subs: dict[str, StrandsTranslator] = {}  # one per sub-agent tool call
        self._text_id: str | None = None
        self._tool_id: str | None = None
        self._reasoning_id: str | None = None
        self._tool_for_interrupt: dict[str, str] = {}  # Strands interrupt id -> tool call id
        self._interrupts: list[Any] = []  # unanswered Strands interrupts, set by the final result

    def translate(self, ev: Any) -> Iterator[BaseEvent]:
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "tool_stream":
            wrapped = ev.get("tool_stream_event") or {}
            parent = (wrapped.get("tool_use") or {}).get("toolUseId", "")
            sub = self._subs.setdefault(parent, StrandsTranslator(nested=True))
            yield from sub.translate(wrapped.get("data"))
        elif "event" in ev:
            yield from self._model_event(ev["event"])
        elif "message" in ev:
            yield from self._message(ev["message"])
        elif "tool_interrupt_event" in ev:
            info = ev["tool_interrupt_event"]
            call_id = (info.get("tool_use") or {}).get("toolUseId")
            for interrupt in info.get("interrupts") or []:
                if call_id:
                    self._tool_for_interrupt[interrupt.id] = call_id
        elif "result" in ev:
            result = ev["result"]
            if getattr(result, "stop_reason", None) == "interrupt":
                self._interrupts = list(getattr(result, "interrupts", None) or [])

    def close(self) -> Iterator[BaseEvent]:
        """End whatever is still open (the stream ended early or failed)."""
        for sub in self._subs.values():
            yield from sub.close()
        yield from self._end_reasoning()
        yield from self._end_text()
        yield from self._end_tool()

    def finished(self, thread_id: str, run_id: str) -> RunFinishedEvent:
        """RUN_FINISHED: with an interrupt outcome when the agent paused for a decision."""
        if not self._interrupts:
            return RunFinishedEvent(thread_id=thread_id, run_id=run_id)
        interrupts = []
        for native in self._interrupts:
            reason = native.reason
            call_id = self._tool_for_interrupt.get(native.id)
            question = reason.get("message") if isinstance(reason, dict) else reason
            interrupts.append(Interrupt(
                id=native.id,
                reason="tool_call" if call_id else "input_required",
                message=str(question) if question else f"The agent is waiting for you ({native.name})",
                tool_call_id=call_id,
                response_schema=APPROVAL_SCHEMA,
            ))
        return RunFinishedEvent(thread_id=thread_id, run_id=run_id, outcome=RunFinishedInterruptOutcome(interrupts=interrupts))

    # -- the raw model stream ------------------------------------------------------------------

    def _model_event(self, e: dict) -> Iterator[BaseEvent]:
        if "contentBlockStart" in e:
            tool_use = e["contentBlockStart"].get("start", {}).get("toolUse")
            if tool_use:
                yield from self._end_reasoning()
                yield from self._end_text()
                yield from self._end_tool()
                self._tool_id = tool_use["toolUseId"]
                yield ToolCallStartEvent(tool_call_id=self._tool_id, tool_call_name=tool_use["name"])
        elif "contentBlockDelta" in e:
            delta = e["contentBlockDelta"].get("delta", {})
            thought = (delta.get("reasoningContent") or {}).get("text")
            if thought:
                if self._nested:
                    return
                if self._reasoning_id is None:
                    yield from self._end_text()
                    self._reasoning_id = str(uuid.uuid4())
                    yield ReasoningStartEvent(message_id=self._reasoning_id)
                    yield ReasoningMessageStartEvent(message_id=self._reasoning_id, role="reasoning")
                yield ReasoningMessageContentEvent(message_id=self._reasoning_id, delta=thought)
            elif delta.get("text"):  # AG-UI requires non-empty deltas
                if self._nested:
                    return
                yield from self._end_reasoning()
                if self._text_id is None:
                    self._text_id = str(uuid.uuid4())
                    yield TextMessageStartEvent(message_id=self._text_id, role="assistant")
                yield TextMessageContentEvent(message_id=self._text_id, delta=delta["text"])
            elif self._tool_id and (args := (delta.get("toolUse") or {}).get("input")):
                yield ToolCallArgsEvent(tool_call_id=self._tool_id, delta=args)
        elif "contentBlockStop" in e:
            yield from self._end_reasoning()
            yield from self._end_text()
            yield from self._end_tool()

    def _message(self, msg: dict) -> Iterator[BaseEvent]:
        """A finished message. Only tool results matter: they are the proof a tool ran (or failed)."""
        if msg.get("role") != "user":
            return
        for block in msg.get("content", []):
            result = block.get("toolResult")
            if result:
                yield ToolCallResultEvent(
                    message_id=str(uuid.uuid4()),
                    tool_call_id=result["toolUseId"],
                    content=_result_text(result.get("content") or []),
                    role="tool",
                    raw_event={"status": result.get("status", "success")},
                )

    def _end_reasoning(self) -> Iterator[BaseEvent]:
        if self._reasoning_id:
            yield ReasoningMessageEndEvent(message_id=self._reasoning_id)
            yield ReasoningEndEvent(message_id=self._reasoning_id)
            self._reasoning_id = None

    def _end_text(self) -> Iterator[BaseEvent]:
        if self._text_id:
            yield TextMessageEndEvent(message_id=self._text_id)
            self._text_id = None

    def _end_tool(self) -> Iterator[BaseEvent]:
        if self._tool_id:
            yield ToolCallEndEvent(tool_call_id=self._tool_id)
            self._tool_id = None


def _result_text(blocks: Iterable[dict]) -> str:
    """A Strands tool result is a list of content blocks; Gentui's TOOL_CALL_RESULT is one string."""
    parts = []
    for block in blocks:
        if "text" in block:
            parts.append(block["text"])
        elif "json" in block:
            parts.append(json.dumps(block["json"], ensure_ascii=False, default=str))
        else:  # image, document, ...: say what it is rather than pretend it is text
            parts.append(f"[{next(iter(block), 'content')}]")
    return "\n".join(parts)
