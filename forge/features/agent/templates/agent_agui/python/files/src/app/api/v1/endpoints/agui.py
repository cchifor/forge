"""AG-UI SSE agent endpoint — the canonical transport for the generated frontend.

This is the **canonical** agent transport that the generated frontend
(``useAgentClient`` on vendored ``canvas-core``) speaks: it POSTs an AG-UI
``RunAgentInput`` (``{threadId, runId, messages, state, tools, context,
forwardedProps}``) and consumes an AG-UI Server-Sent Events stream
(single-channel ``data: {json}\\n\\n`` frames; ``RUN_STARTED`` →
``TEXT_MESSAGE_*`` → ``TOOL_CALL_*`` → ``RUN_FINISHED``).

The legacy WebSocket endpoint at ``/api/v1/ws/agent`` (``endpoints/agent.py``)
stays available as a raw/typed-event transport, but it is NOT what the
generated frontend talks to — SSE is.

The whole SSE protocol is upstream: ``pydantic_ai.ui.ag_ui.AGUIAdapter``
reads the request body, runs the agent, and returns a Starlette SSE
``StreamingResponse`` whose frames are exactly what ``canvas-core`` parses
(SCREAMING_CASE ``type`` + camelCase aliases). We add no event-translation
code — only the agent build (shared with the WS runner) + auth gating.

Frontend/deferred tools carried in the body's ``tools`` are turned into a
pydantic-ai ``ExternalToolset`` by the adapter automatically. See
``AGENT_AGUI_HARDENING.md`` for the deferred-tool RESUME gap and other
deferred production concerns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from forge_core.security.auth import get_current_user

# The endpoint spends LLM budget and invokes server-side tools, so it carries
# the same auth posture as the already-gated ``/api/v1/tools`` router (NOT the
# ungated echo WebSocket). ``get_current_user`` raises 401 when no valid token
# is present. In a no-auth/dev project this dependency is a permissive no-op.
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("")
async def run_agent_agui(request: Request):
    """Run one agent turn and stream AG-UI SSE events.

    ``AGUIAdapter.dispatch_request`` is an async classmethod that reads the
    raw request body itself (so we pass the unparsed ``Request``, not a bound
    body model), constructs the run, executes the agent, and returns a
    Starlette SSE ``StreamingResponse``.
    """
    # Lazy import so non-agui imports of this package don't pay the
    # pydantic-ai import cost.
    from pydantic_ai.ui.ag_ui import AGUIAdapter  # type: ignore

    from app.agents.llm_runner import build_agent

    agent = build_agent()
    return await AGUIAdapter.dispatch_request(request, agent=agent)
