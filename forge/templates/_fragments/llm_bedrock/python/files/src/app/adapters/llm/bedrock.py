"""AWS Bedrock adapter for LlmProviderPort.

Uses ``aioboto3`` for async S3/Bedrock calls. Bedrock wraps multiple
model providers (Anthropic, Meta, Amazon Nova); the adapter routes
based on the ``model`` parameter passed to ``complete_stream``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import aioboto3

from app.ports.llm import LlmMessage, LlmProviderPort, LlmStreamChunk, LlmTool


class BedrockAdapter(LlmProviderPort):
    def __init__(self, region: str) -> None:
        self._region = region
        self._session = aioboto3.Session()

    async def complete_stream(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        tools: list[LlmTool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LlmStreamChunk]:
        body = _build_body(model, messages, tools, temperature, max_tokens)
        async with self._session.client("bedrock-runtime", region_name=self._region) as client:
            response = await client.invoke_model_with_response_stream(
                modelId=model,
                body=json.dumps(body).encode("utf-8"),
            )
            async for event in response["body"]:
                chunk_bytes = event.get("chunk", {}).get("bytes", b"")
                if not chunk_bytes:
                    continue
                payload = json.loads(chunk_bytes)
                # Bedrock's shape varies by model — this handles
                # Anthropic-on-Bedrock; Nova and Llama routes get added
                # in 1.0.0a3.
                if payload.get("type") == "content_block_delta":
                    delta = payload.get("delta", {}).get("text", "")
                    if delta:
                        yield LlmStreamChunk(text_delta=delta)

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


def _build_body(
    model: str,
    messages: list[LlmMessage],
    tools: list[LlmTool] | None,
    temperature: float,
    max_tokens: int | None,
) -> dict[str, Any]:
    """Build the Bedrock invoke body. Anthropic-on-Bedrock format is the
    default; other routing lands with 1.0.0a3's ADR for multi-model
    Bedrock dispatch."""
    body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens or 4096,
        "temperature": temperature,
        "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
    }
    system = next((m.content for m in messages if m.role == "system"), None)
    if system:
        body["system"] = system
    if tools:
        body["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
    return body
