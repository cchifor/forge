"""Runner dispatch for the agent WebSocket.

Prefers an LLM-backed runner when the ``agent`` feature has shipped
``llm_runner.py``. Otherwise falls back to the echo runner so the
WebSocket contract remains exerciseable without any LLM dependency.

The contract both runners implement:

    async def run_agent(
        *,
        conversation_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        user_prompt: str,
    ) -> AsyncIterator[AgentEvent]:
        ...

The runner yields a sequence of :class:`AgentEvent` objects; the WebSocket
handler serializes them and pushes each as a JSON frame.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _select_runner():  # returns the run_agent coroutine generator function
    """Import-time selection: use llm_runner if it exists, else echo_agent.

    Module-level import so the decision is made once per process; no
    per-request cost. Silent fallback — the decision is logged at INFO
    so operators know which runner is active.
    """
    try:
        from app.agents.llm_runner import run_agent  # type: ignore
    except ImportError:
        from app.agents.echo_agent import run_echo_agent as run_agent
        logger.info("agent runner = echo (llm_runner not present)")
        return run_agent
    logger.info("agent runner = llm (pydantic-ai)")
    return run_agent


run_agent = _select_runner()

__all__ = ["run_agent"]
