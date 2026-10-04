"""SSE client: POSTs a RunAgentInput to the backend and yields typed AG-UI events."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from ag_ui.core import Event, RunAgentInput, UserMessage
from pydantic import TypeAdapter, ValidationError

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)


class AguiClient:
    def __init__(self, url: str) -> None:
        self.url = url

    async def run(
        self, thread_id: str, text: str, forwarded_props: dict[str, Any] | None = None
    ) -> AsyncIterator[Event]:
        """Send one user message; yield events until the server closes the stream.

        We send only the NEW message: this backend keeps the history per thread_id
        (AG-UI allows either approach).
        """
        body = RunAgentInput(
            thread_id=thread_id,
            run_id=str(uuid.uuid4()),
            state={},
            messages=[UserMessage(id=str(uuid.uuid4()), role="user", content=text)],
            tools=[],
            context=[],
            forwarded_props=forwarded_props or {},
        ).model_dump(by_alias=True, exclude_none=True)

        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10)) as http:
            async with http.stream(
                "POST", self.url, json=body, headers={"accept": "text/event-stream"}
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        yield _event_adapter.validate_python(json.loads(line[5:]))
                    except (ValidationError, json.JSONDecodeError):
                        continue  # unknown/malformed event: skip rather than crash the UI
