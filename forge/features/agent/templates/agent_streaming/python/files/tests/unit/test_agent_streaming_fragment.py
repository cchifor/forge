"""Fragment smoke tests for `agent_streaming`.

Minimal: asserts the WebSocket endpoint module and runner-dispatch
module import cleanly, and that the event classes serialise.

Serialisation specifically asserts the transitional dual-discriminator
contract: every frame must carry BOTH ``type`` (legacy) and ``kind``
(canonical, mirrors the canvas ``AgUiEvent`` codegen) with byte-equal
values. The ``kind`` field is the canonical wire discriminator going
forward; ``type`` survives one release for backward compatibility and
is scheduled for removal in the next minor.
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
    # Both discriminators must be present and equal during the
    # type -> kind transition. The legacy ``type`` survives one
    # release; ``kind`` is the canonical wire field going forward.
    assert dumped["type"] == "conversation_created"
    assert dumped["kind"] == "conversation_created"
    assert isinstance(dumped["conversation_id"], str)


def test_agent_events_accept_kind_alias_on_input() -> None:
    """Inbound frames using the canonical ``kind`` field validate as well."""
    from app.agents.events import ConversationCreated

    conv_id = uuid.uuid4()
    ev = ConversationCreated.model_validate(
        {"kind": "conversation_created", "conversation_id": str(conv_id)}
    )
    assert ev.conversation_id == conv_id
    # Round-trips through the dual-emission serializer.
    dumped = ev.model_dump(mode="json")
    assert dumped["type"] == "conversation_created"
    assert dumped["kind"] == "conversation_created"
