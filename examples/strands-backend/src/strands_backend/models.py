"""Model factory: the one place that decides which LLM backs the agents.

Returns a "<provider>/<model>" string, which create_harness() resolves itself.
Need custom endpoints or credentials? Return a strands Model instance here instead;
nothing else in the codebase changes.

Exception: `ollama/...` returns OllamaThinkingModel, because the stock Strands Ollama
provider drops the model's `thinking` field, so the chain of thought never reaches the UI.
"""

import os
from collections.abc import AsyncGenerator
from typing import Any

import ollama
from strands.models.ollama import OllamaModel

from strands_backend.config import Settings, get_settings


class OllamaThinkingModel(OllamaModel):
    """OllamaModel that streams Ollama's `thinking` text as Strands `reasoningContent`."""

    def _format_request_message_contents(self, role: str, content: Any) -> list[dict[str, Any]]:
        if "reasoningContent" in content:  # Ollama has no place for past reasoning; skip it
            return []
        return super()._format_request_message_contents(role, content)

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncGenerator:  # type: ignore[override]
        request = self.format_request(messages, tool_specs, system_prompt)
        client = ollama.AsyncClient(self.host, **self.client_args)
        response = await client.chat(**request)

        yield self.format_chunk({"chunk_type": "message_start"})
        thinking = False  # is a reasoning block currently open?
        text_open = False
        tool_requested = False
        event = None

        async for event in response:
            if event.message.thinking:
                if not thinking:
                    yield {"contentBlockStart": {"start": {}}}
                    thinking = True
                yield {
                    "contentBlockDelta": {"delta": {"reasoningContent": {"text": event.message.thinking}}}
                }
            if event.message.content or event.message.tool_calls:
                if thinking:
                    yield {"contentBlockStop": {}}
                    thinking = False
                if not text_open:
                    yield self.format_chunk({"chunk_type": "content_start", "data_type": "text"})
                    text_open = True
            for tool_call in event.message.tool_calls or []:
                yield self.format_chunk({"chunk_type": "content_start", "data_type": "tool", "data": tool_call})
                yield self.format_chunk({"chunk_type": "content_delta", "data_type": "tool", "data": tool_call})
                yield self.format_chunk({"chunk_type": "content_stop", "data_type": "tool", "data": tool_call})
                tool_requested = True
            if event.message.content:
                yield self.format_chunk(
                    {"chunk_type": "content_delta", "data_type": "text", "data": event.message.content}
                )

        if thinking:
            yield {"contentBlockStop": {}}
        if text_open:
            yield self.format_chunk({"chunk_type": "content_stop", "data_type": "text"})
        stop = "tool_use" if tool_requested else (event.done_reason if event else None)
        yield self.format_chunk({"chunk_type": "message_stop", "data": stop})
        if event is not None:
            yield self.format_chunk({"chunk_type": "metadata", "data": event})


def make_model(settings: Settings | None = None) -> Any:
    model = (settings or get_settings()).model
    provider, _, name = model.partition("/")
    if provider == "ollama":
        return OllamaThinkingModel(
            host=os.environ.get("OLLAMA_HOST"),
            model_id=name,
            additional_args={"think": True},  # ask the model to return its reasoning
        )
    return model
