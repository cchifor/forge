"""Anthropic adapter for LlmProviderPort.

Uses the official ``anthropic`` async client. The Anthropic message
shape is slightly different from OpenAI (system prompts are a
top-level parameter, not a message), so the adapter extracts the
leading system message and passes the rest untouched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.ports.llm import LlmMessage, LlmProviderPort, LlmStreamChunk, LlmTool


class AnthropicAdapter(LlmProviderPort):
    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete_stream(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        tools: list[LlmTool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LlmStreamChunk]:
        system_prompt, rest = _extract_system(messages)
        kwargs: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in rest],
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                # Map Anthropic event types to the port's chunk shape.
                event_type = getattr(event, "type", "")
                if event_type == "content_block_delta":
                    delta = getattr(event.delta, "text", "") or ""
                    if delta:
                        yield LlmStreamChunk(text_delta=delta)
                elif event_type == "message_stop":
                    yield LlmStreamChunk(finish_reason="stop")

    async def complete(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        tools: list[LlmTool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LlmMessage:
        parts: list[str] = []
        async for chunk in self.complete_stream(
            model=model, messages=messages, tools=tools,
            temperature=temperature, max_tokens=max_tokens,
        ):
            parts.append(chunk.text_delta)
        return LlmMessage(role="assistant", content="".join(parts))


def _extract_system(messages: list[LlmMessage]) -> tuple[str | None, list[LlmMessage]]:
    """Pull the leading system message out, if present."""
    if messages and messages[0].role == "system":
        return messages[0].content, messages[1:]
    return None, list(messages)
