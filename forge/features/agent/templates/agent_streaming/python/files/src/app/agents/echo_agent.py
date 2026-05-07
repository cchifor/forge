"""Echo agent: a no-LLM implementation of the agent contract.

Takes a user prompt and streams it back character-by-character as
``text_delta`` events, with realistic pacing. Used to validate the
WebSocket + event protocol end-to-end *before* a real LLM provider is
plugged in. A future `agent` feature swaps this for a pydantic-ai run
over the tool registry.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from app.agents.events import (
    AgentEvent,
    AgentStatus,
    TextDelta,
    ToolCallStarted,
    ToolResult,
)


async def run_echo_agent(
    *,
    conversation_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    user_prompt: str,
    delay_s: float = 0.02,
) -> AsyncIterator[AgentEvent]:
    """Yield a realistic sequence of events for a given prompt.

    - "thinking" status kicks off the turn.
    - If the prompt starts with ``/tool <name>``, synthesize a tool-call
      round-trip so UI flows can exercise tool-call rendering without a
      real LLM.
    - Otherwise stream the echoed content token-by-token, then close with
      a "done" status.
    """
    yield AgentStatus(conversation_id=conversation_id, status="thinking")

    stripped = user_prompt.strip()
    if stripped.startswith("/tool "):
        tool_name = stripped.removeprefix("/tool ").split(" ", 1)[0] or "current_datetime"
        tool_call_id = uuid.uuid4()
        yield ToolCallStarted(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments={},
        )
        await asyncio.sleep(0.1)
        # Hit the tool registry if we can; fall back to a synthetic result.
        try:
            from app.agents import tool_registry  # type: ignore

            tool = tool_registry.get(tool_name)
            result = await tool.invoke()
        except Exception as e:  # noqa: BLE001
            yield ToolResult(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                result=None,
                error=str(e),
            )
            yield AgentStatus(conversation_id=conversation_id, status="error", detail=str(e))
            return
        yield ToolResult(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            result=result,
        )
        yield AgentStatus(conversation_id=conversation_id, status="done")
        return

    # Plain-text echo: stream character-by-character so UIs can exercise
    # their delta-accumulation code path.
    for ch in user_prompt:
        yield TextDelta(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            delta=ch,
        )
        await asyncio.sleep(delay_s)
    yield AgentStatus(conversation_id=conversation_id, status="done")
