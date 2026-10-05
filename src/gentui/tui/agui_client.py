"""SSE client: POSTs a RunAgentInput to the backend and yields typed AG-UI events."""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from ag_ui.core import (
    AssistantMessage, Event, EventType, FunctionCall, Message, ResumeEntry, RunAgentInput,
    ToolCall, ToolMessage, UserMessage,
)
from pydantic import TypeAdapter, ValidationError

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)


class BackendError(Exception):
    """The backend could not be reached or refused the request. The message is safe to show the user."""


class AguiClient:
    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        send_history: bool = False,
    ) -> None:
        self.url = url
        # False (default): only the newest message; the backend keeps history per thread_id.
        # True: send the whole conversation every time, for stateless backends.
        self.send_history = send_history
        self._history: dict[str, list[Message]] = {}  # thread_id -> messages rebuilt from events
        self._open_calls: dict[str, tuple[str, str]] = {}  # tool_call_id -> (name, raw args)
        self._open_text: dict[str, str] = {}  # message_id -> text so far
        self.headers = headers or {}
        self.on_raw: Callable[[str], None] | None = None  # sees every SSE payload, unparsed
        self.timeout = timeout  # None = no read timeout (agents can think for a long time)

    async def run(
        self,
        thread_id: str,
        text: str,
        forwarded_props: dict[str, Any] | None = None,
        resume: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """Send one user message (or, with `resume`, answer open interrupts); yield events
        until the server closes the stream.

        `resume` is a list of {"interruptId", "status": "resolved"|"cancelled", "payload"}
        and sends no new message: it continues the interrupted run on the same thread.

        With `send_history` the whole conversation is sent, otherwise only the new message.
        """
        history = self._history.setdefault(thread_id, [])
        new_user = UserMessage(id=str(uuid.uuid4()), role="user", content=text)
        if text and not resume:
            history.append(new_user)
        if self.send_history:
            messages: list[Message] = list(history)
        else:
            messages = [] if resume else [new_user]
        body = RunAgentInput(
            thread_id=thread_id,
            run_id=str(uuid.uuid4()),
            state={},
            messages=messages,
            tools=[],
            context=[],
            forwarded_props=forwarded_props or {},
            resume=[ResumeEntry.model_validate(r) for r in resume] if resume else None,
        ).model_dump(by_alias=True, exclude_none=True)

        async for line in self._stream_lines(body):
            if not line.startswith("data:"):
                continue
            if self.on_raw:
                self.on_raw(line[5:].strip())
            try:
                event = _event_adapter.validate_python(json.loads(line[5:]))
            except (ValidationError, json.JSONDecodeError):
                continue  # unknown/malformed event: skip rather than crash the UI
            if self.send_history:
                self._record(history, event)
            yield event

    async def _stream_lines(self, body: dict[str, Any]) -> AsyncIterator[str]:
        """The transport: POST the RunAgentInput and yield the response's SSE lines.
        Subclasses replace this (see `AgentCoreClient`); everything else is shared."""
        headers = {"accept": "text/event-stream", **self.headers}
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=10)) as http:
            async with http.stream("POST", self.url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    yield line

    def _record(self, history: list[Message], ev: Event) -> None:
        """Rebuild the assistant / tool side of the conversation from the event stream."""
        t = ev.type
        if t == EventType.TEXT_MESSAGE_START:
            self._open_text[ev.message_id] = ""
        elif t == EventType.TEXT_MESSAGE_CONTENT and ev.message_id in self._open_text:
            self._open_text[ev.message_id] += ev.delta
        elif t == EventType.TEXT_MESSAGE_END and ev.message_id in self._open_text:
            text = self._open_text.pop(ev.message_id)
            if text:
                history.append(AssistantMessage(id=ev.message_id, role="assistant", content=text))
        elif t == EventType.TOOL_CALL_START:
            self._open_calls[ev.tool_call_id] = (ev.tool_call_name, "")
        elif t == EventType.TOOL_CALL_ARGS and ev.tool_call_id in self._open_calls:
            name, args = self._open_calls[ev.tool_call_id]
            self._open_calls[ev.tool_call_id] = (name, args + ev.delta)
        elif t == EventType.TOOL_CALL_END and ev.tool_call_id in self._open_calls:
            name, args = self._open_calls.pop(ev.tool_call_id)
            call = ToolCall(id=ev.tool_call_id, type="function", function=FunctionCall(name=name, arguments=args or "{}"))
            history.append(AssistantMessage(id=str(uuid.uuid4()), role="assistant", tool_calls=[call]))
        elif t == EventType.TOOL_CALL_RESULT:
            history.append(ToolMessage(id=ev.message_id, role="tool", tool_call_id=ev.tool_call_id, content=ev.content))
