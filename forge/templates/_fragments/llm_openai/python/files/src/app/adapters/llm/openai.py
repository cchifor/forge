"""OpenAI adapter for LlmProviderPort.

Uses the official ``openai`` async client. Stream chunks are translated
to the port's ``LlmStreamChunk`` shape so callers don't leak the
provider-specific event model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.ports.llm import LlmMessage, LlmProviderPort, LlmStreamChunk, LlmTool


class OpenAIAdapter(LlmProviderPort):
    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)

    async def complete_stream(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        tools: list[LlmTool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LlmStreamChunk]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [_to_openai_message(m) for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            yield LlmStreamChunk(
                text_delta=delta.content or "",
                tool_call_delta=_tool_call_to_dict(delta.tool_calls),
                finish_reason=choice.finish_reason,
                usage=None,
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


def _to_openai_message(m: LlmMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = m.tool_calls
    if m.name:
        out["name"] = m.name
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    return out


def _to_openai_tool(t: LlmTool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        },
    }


def _tool_call_to_dict(tool_calls: Any) -> dict[str, Any] | None:
    if not tool_calls:
        return None
    # Stream deltas: OpenAI sends incremental tool_calls. Keep the raw
    # shape; the caller is responsible for accumulating.
    return [tc.model_dump(exclude_none=True) for tc in tool_calls]  # type: ignore[no-any-return]
