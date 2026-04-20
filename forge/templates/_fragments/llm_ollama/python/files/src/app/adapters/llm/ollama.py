"""Ollama adapter for LlmProviderPort.

Uses the ``ollama`` async client. Ollama's API looks close to OpenAI's
(role/content messages, streaming deltas) so the translation is
mostly 1:1. Tool calling is supported in recent Ollama versions via
the ``tools`` parameter.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ollama import AsyncClient

from app.ports.llm import LlmMessage, LlmProviderPort, LlmStreamChunk, LlmTool


class OllamaAdapter(LlmProviderPort):
    def __init__(self, host: str) -> None:
        self._client = AsyncClient(host=host)

    async def complete_stream(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        tools: list[LlmTool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LlmStreamChunk]:
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": options,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]

        async for chunk in await self._client.chat(**kwargs):
            message = chunk.get("message", {})
            text = message.get("content") or ""
            yield LlmStreamChunk(
                text_delta=text,
                tool_call_delta=message.get("tool_calls"),
                finish_reason="stop" if chunk.get("done") else None,
            )

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
