"""LLM-backed agent runner (pydantic-ai).

Implements the same ``run_agent`` contract as :mod:`app.agents.echo_agent`,
so :mod:`app.agents.runner` picks it up automatically when this module is
present. The echo agent remains available as a fallback if pydantic-ai
isn't installed yet (e.g., on a fresh clone before ``uv sync``).

Provider selection is env-driven — users flip ``LLM_PROVIDER`` between
anthropic / openai / google / openrouter without touching code. Missing
API keys produce a clean error event on the WebSocket, not a crash.

Kept deliberately simple for v1: a single agent run per WebSocket message,
tool-call events reconstructed from ``RunResult.new_messages()``, final
response streamed as chunked ``text_delta`` events. Full streaming via
``agent.iter()`` is a follow-up when the protocol adds streaming-rendering
hints.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.agents.events import (
    AgentEvent,
    AgentStatus,
    ErrorEvent,
    TextDelta,
    ToolCallStarted,
    ToolResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant running inside a forge-generated service. "
    "Use the registered tools when they can answer the user's question "
    "more accurately than you could unaided. Keep responses concise."
)


class _RunnerConfig:
    """Resolved agent configuration, computed once per process."""

    def __init__(self) -> None:
        self.provider = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
        self.model_name = os.environ.get("LLM_MODEL", "").strip() or _default_model(self.provider)
        self.system_prompt = os.environ.get("AGENT_SYSTEM_PROMPT", _DEFAULT_SYSTEM_PROMPT)
        self.chunk_size = int(os.environ.get("AGENT_STREAM_CHUNK_SIZE", "40"))
        self.chunk_delay_s = float(os.environ.get("AGENT_STREAM_CHUNK_DELAY", "0.03"))


def _default_model(provider: str) -> str:
    return {
        "anthropic": "claude-sonnet-4-5",
        "openai": "gpt-4o-mini",
        "google": "gemini-1.5-flash",
        "openrouter": "anthropic/claude-sonnet-4-5",
    }.get(provider, "claude-sonnet-4-5")


_agent_singleton: Any | None = None
_config_singleton: _RunnerConfig | None = None


def _build_agent():
    """Construct the pydantic-ai Agent. Tools are registered from the
    process-wide ``ToolRegistry``.

    Lazy — the Agent is built on first request so a project that never hits
    /ws/agent doesn't pay for pydantic-ai import cost at startup.
    """
    from pydantic_ai import Agent  # type: ignore

    cfg = _config_singleton or _RunnerConfig()
    model = _resolve_model(cfg)

    agent = Agent(model, system_prompt=cfg.system_prompt)

    # Bridge every tool in the registry into pydantic-ai.
    try:
        from app.agents import tool_registry  # type: ignore
    except ImportError:
        tool_registry = None  # type: ignore

    if tool_registry is not None:
        for tool in tool_registry.list():
            _register_tool(agent, tool)

    return agent


def _resolve_model(cfg: _RunnerConfig):
    """Return a pydantic-ai model object for the configured provider.

    Per-provider imports so a service running on Anthropic doesn't need
    the OpenAI SDK installed.
    """
    if cfg.provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel  # type: ignore

        return AnthropicModel(cfg.model_name)
    if cfg.provider == "openai":
        from pydantic_ai.models.openai import OpenAIChatModel  # type: ignore

        return OpenAIChatModel(cfg.model_name)
    if cfg.provider == "google":
        from pydantic_ai.models.google import GoogleModel  # type: ignore

        return GoogleModel(cfg.model_name)
    if cfg.provider == "openrouter":
        # OpenRouter is OpenAI-compatible.
        from pydantic_ai.models.openai import OpenAIChatModel  # type: ignore
        from pydantic_ai.providers.openrouter import OpenRouterProvider  # type: ignore

        provider = OpenRouterProvider(api_key=os.environ.get("OPENROUTER_API_KEY", ""))
        return OpenAIChatModel(cfg.model_name, provider=provider)
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {cfg.provider!r}")


def _register_tool(agent, tool) -> None:
    """Bind one forge ``Tool`` as a pydantic-ai tool.

    pydantic-ai introspects the function signature for its schema; we wrap
    the registered handler so it can be called with matching kwargs.
    """

    async def _wrapper(**kwargs: Any) -> Any:
        return await tool.invoke(**kwargs)

    _wrapper.__name__ = tool.name
    _wrapper.__doc__ = tool.description
    agent.tool_plain(_wrapper)


async def run_agent(
    *,
    conversation_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    user_prompt: str,
) -> AsyncIterator[AgentEvent]:
    """Execute one agent turn and stream events over the WebSocket.

    Primary path uses ``agent.iter()`` for true per-delta text streaming
    and real-time tool-call events. If the installed pydantic-ai version
    exposes a different event surface, we fall through to a non-streaming
    ``agent.run()`` + chunked-output + message-replay path so the turn
    still completes with coherent events.
    """
    global _agent_singleton, _config_singleton

    yield AgentStatus(conversation_id=conversation_id, status="thinking")

    try:
        if _config_singleton is None:
            _config_singleton = _RunnerConfig()
        if _agent_singleton is None:
            _agent_singleton = _build_agent()
    except ImportError as e:
        yield ErrorEvent(
            conversation_id=conversation_id,
            message=f"pydantic-ai import failed: {e}. Run `uv sync` to install.",
        )
        yield AgentStatus(conversation_id=conversation_id, status="error", detail=str(e))
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("agent build failed")
        yield ErrorEvent(conversation_id=conversation_id, message=f"agent setup failed: {e}")
        yield AgentStatus(conversation_id=conversation_id, status="error", detail=str(e))
        return

    agent = _agent_singleton
    cfg = _config_singleton

    # Streaming primary. The inner helper signals unsupported via ``NotImplementedError``
    # so we know to fall through to the non-streaming path without losing the turn.
    try:
        async for event in _stream_iter(agent, user_prompt, conversation_id, assistant_message_id):
            yield event
        yield AgentStatus(conversation_id=conversation_id, status="done")
        return
    except NotImplementedError:
        logger.info("streaming path unsupported; falling back to non-streaming")
    except Exception as e:  # noqa: BLE001
        logger.exception("streaming path failed; falling back")
        # Best-effort fallback — don't give up after a streaming hiccup.

    # Non-streaming fallback: single run, chunked text, tool events replayed from log.
    try:
        result = await agent.run(user_prompt)
    except Exception as e:  # noqa: BLE001
        logger.exception("agent run failed")
        yield ErrorEvent(conversation_id=conversation_id, message=f"agent run failed: {e}")
        yield AgentStatus(conversation_id=conversation_id, status="error", detail=str(e))
        return

    try:
        async for event in _replay_tool_events(result, conversation_id, assistant_message_id):
            yield event
    except Exception as e:  # noqa: BLE001
        logger.debug("tool event reconstruction failed: %s", e)

    text = getattr(result, "output", None) or getattr(result, "data", "") or ""
    text = str(text)
    if not text:
        text = "(empty response)"
    for i in range(0, len(text), cfg.chunk_size):
        chunk = text[i : i + cfg.chunk_size]
        yield TextDelta(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            delta=chunk,
        )
        if cfg.chunk_delay_s > 0:
            await asyncio.sleep(cfg.chunk_delay_s)

    yield AgentStatus(conversation_id=conversation_id, status="done")


async def _stream_iter(
    agent: Any,
    user_prompt: str,
    conversation_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
) -> AsyncIterator[AgentEvent]:
    """Iterate `agent.iter()` and translate pydantic-ai events to forge events.

    Raises :class:`NotImplementedError` if the installed pydantic-ai lacks the
    event classes we need — caller handles fallback.
    """
    try:
        from pydantic_ai import Agent as _Agent  # type: ignore
        from pydantic_ai.messages import (  # type: ignore
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            PartDeltaEvent,
            TextPartDelta,
        )
    except ImportError as e:
        raise NotImplementedError(f"pydantic-ai streaming API missing: {e}") from e

    if not hasattr(_Agent, "is_model_request_node") or not hasattr(_Agent, "is_call_tools_node"):
        raise NotImplementedError("pydantic-ai node detection helpers missing")

    async with agent.iter(user_prompt) as run:
        async for node in run:
            if _Agent.is_model_request_node(node):
                async for ev in _drain_model_request(
                    node, run, conversation_id, assistant_message_id, PartDeltaEvent, TextPartDelta
                ):
                    yield ev
            elif _Agent.is_call_tools_node(node):
                async for ev in _drain_tool_calls(
                    node,
                    run,
                    conversation_id,
                    assistant_message_id,
                    FunctionToolCallEvent,
                    FunctionToolResultEvent,
                ):
                    yield ev


async def _drain_model_request(
    node: Any,
    run: Any,
    conversation_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    PartDeltaEvent: type,
    TextPartDelta: type,
) -> AsyncIterator[AgentEvent]:
    async with node.stream(run.ctx) as request_stream:
        async for event in request_stream:
            if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                delta = getattr(event.delta, "content_delta", "")
                if delta:
                    yield TextDelta(
                        conversation_id=conversation_id,
                        message_id=assistant_message_id,
                        delta=delta,
                    )


async def _drain_tool_calls(
    node: Any,
    run: Any,
    conversation_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    FunctionToolCallEvent: type,
    FunctionToolResultEvent: type,
) -> AsyncIterator[AgentEvent]:
    # Track id → (tool_name, event_uuid) so we can correlate result events back.
    pending: dict[str, tuple[str, uuid.UUID]] = {}
    async with node.stream(run.ctx) as tool_stream:
        async for event in tool_stream:
            if isinstance(event, FunctionToolCallEvent):
                part = getattr(event, "part", None) or event
                tool_name = str(getattr(part, "tool_name", "unknown"))
                raw_call_id = str(getattr(part, "tool_call_id", uuid.uuid4()))
                try:
                    event_uuid = uuid.UUID(raw_call_id)
                except ValueError:
                    event_uuid = uuid.uuid4()
                arguments = getattr(part, "args", None) or {}
                if not isinstance(arguments, dict):
                    try:
                        arguments = dict(arguments)
                    except Exception:  # noqa: BLE001
                        arguments = {"_raw": str(arguments)}
                pending[raw_call_id] = (tool_name, event_uuid)
                yield ToolCallStarted(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    tool_call_id=event_uuid,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            elif isinstance(event, FunctionToolResultEvent):
                raw_call_id = str(getattr(event, "tool_call_id", ""))
                tool_name, event_uuid = pending.get(raw_call_id, ("unknown", uuid.uuid4()))
                result_obj = getattr(event, "result", None)
                content = getattr(result_obj, "content", None) if result_obj is not None else None
                yield ToolResult(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    tool_call_id=event_uuid,
                    tool_name=tool_name,
                    result=content,
                )


async def _replay_tool_events(
    result: Any,
    conversation_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
) -> AsyncIterator[AgentEvent]:
    """Pull ToolCall / ToolReturn parts from the run's message log."""
    messages = _new_messages(result)
    pending: dict[str, tuple[str, dict]] = {}
    for msg in messages:
        parts = getattr(msg, "parts", None) or []
        for part in parts:
            part_kind = getattr(part, "part_kind", None) or type(part).__name__
            if "ToolCall" in part_kind or "tool-call" in str(part_kind).lower():
                tool_call_id = getattr(part, "tool_call_id", None) or str(uuid.uuid4())
                pending[tool_call_id] = (
                    str(getattr(part, "tool_name", "unknown")),
                    getattr(part, "args", {}) or getattr(part, "arguments", {}) or {},
                )
                yield ToolCallStarted(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    tool_call_id=uuid.UUID(tool_call_id) if _is_uuid(tool_call_id) else uuid.uuid4(),
                    tool_name=pending[tool_call_id][0],
                    arguments=pending[tool_call_id][1] if isinstance(pending[tool_call_id][1], dict) else {},
                )
            elif "ToolReturn" in part_kind or "tool-return" in str(part_kind).lower():
                tool_call_id = getattr(part, "tool_call_id", None)
                name, _args = pending.get(tool_call_id, ("unknown", {}))
                yield ToolResult(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    tool_call_id=uuid.UUID(tool_call_id) if _is_uuid(tool_call_id) else uuid.uuid4(),
                    tool_name=name,
                    result=getattr(part, "content", None),
                )


def _new_messages(result: Any) -> list:
    fn = getattr(result, "new_messages", None)
    if callable(fn):
        try:
            return list(fn())
        except Exception:  # noqa: BLE001
            return []
    msgs = getattr(result, "all_messages", None)
    if callable(msgs):
        try:
            return list(msgs())
        except Exception:  # noqa: BLE001
            return []
    return []


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False
