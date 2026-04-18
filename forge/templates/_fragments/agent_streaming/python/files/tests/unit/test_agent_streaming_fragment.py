"""Fragment smoke tests for `agent_streaming`.

Minimal: asserts the WebSocket endpoint module and runner-dispatch
module import cleanly, and that the event classes serialise.
"""

from __future__ import annotations

import uuid


def test_endpoint_module_imports() -> None:
    from app.api.v1.endpoints import agent  # noqa: F401


def test_runner_module_imports() -> None:
    from app.agents import runner  # noqa: F401


def test_agent_events_serialise() -> None:
    from app.agents.events import ConversationCreated

    ev = ConversationCreated(conversation_id=uuid.uuid4())
    dumped = ev.model_dump(mode="json")
    assert dumped["type"] == "conversation_created"
    assert isinstance(dumped["conversation_id"], str)
