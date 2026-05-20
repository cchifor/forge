"""Tests for the agent_streaming WebSocket event envelope.

Initiative #4 — unify the agent / AG-UI runtime protocol on a single
``kind`` discriminator. The shipped backend models (under the
``agent_streaming`` template) historically used ``type`` on the wire;
the canvas ``AgUiEvent`` codegen uses ``kind``. To migrate without
breaking pinned consumers, the model serializer emits BOTH fields for
one release and the validator accepts either as input.

These tests load the template's ``events.py`` directly off disk so they
run inside the forge repo's pytest suite without needing a generated
project. Same pattern as ``tests/test_mcp_audit.py``.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

_EVENTS_PATH = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "agent"
    / "templates"
    / "agent_streaming"
    / "python"
    / "files"
    / "src"
    / "app"
    / "agents"
    / "events.py"
)


def _load_events_module():
    """Import the agent_streaming events module by file path."""
    spec = importlib.util.spec_from_file_location("agent_events_under_test", _EVENTS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_events_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def events():
    return _load_events_module()


# ---------------------------------------------------------------------------
# Discriminator surface — every concrete event class must round-trip with
# both `type` and `kind` on the wire during the transition.
# ---------------------------------------------------------------------------


def _every_event_factory(events_mod):
    """Yield (class, factory-callable) for every concrete event."""
    conv_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    tool_call_id = uuid.uuid4()
    return [
        (events_mod.ConversationCreated, lambda: events_mod.ConversationCreated(conversation_id=conv_id)),
        (events_mod.UserPromptReceived, lambda: events_mod.UserPromptReceived(
            conversation_id=conv_id, message_id=msg_id, content="hi"
        )),
        (events_mod.TextDelta, lambda: events_mod.TextDelta(
            conversation_id=conv_id, message_id=msg_id, delta="x"
        )),
        (events_mod.ToolCallStarted, lambda: events_mod.ToolCallStarted(
            conversation_id=conv_id,
            message_id=msg_id,
            tool_call_id=tool_call_id,
            tool_name="t",
            arguments={"a": 1},
        )),
        (events_mod.ToolResult, lambda: events_mod.ToolResult(
            conversation_id=conv_id,
            message_id=msg_id,
            tool_call_id=tool_call_id,
            tool_name="t",
            result={"ok": True},
        )),
        (events_mod.AgentStatus, lambda: events_mod.AgentStatus(
            conversation_id=conv_id, status="thinking"
        )),
        (events_mod.ErrorEvent, lambda: events_mod.ErrorEvent(
            conversation_id=conv_id, message="boom"
        )),
    ]


class TestDualDiscriminatorSerialisation:
    """Every concrete event class must emit BOTH ``type`` and ``kind`` on the wire."""

    def test_every_event_emits_both_keys(self, events) -> None:
        for klass, factory in _every_event_factory(events):
            dumped = factory().model_dump(mode="json")
            assert "type" in dumped, f"{klass.__name__}: missing legacy `type` discriminator"
            assert "kind" in dumped, f"{klass.__name__}: missing canonical `kind` discriminator"
            assert dumped["type"] == dumped["kind"], (
                f"{klass.__name__}: type/kind drift on the wire — would break the transition"
            )

    def test_kind_value_matches_class_literal(self, events) -> None:
        # The literal slug defined on each class is the canonical wire value.
        # If the dual-emission helper ever stops mirroring it, every existing
        # consumer pinned to a specific event slug would silently break.
        expected = {
            events.ConversationCreated: "conversation_created",
            events.UserPromptReceived: "user_prompt",
            events.TextDelta: "text_delta",
            events.ToolCallStarted: "tool_call",
            events.ToolResult: "tool_result",
            events.AgentStatus: "agent_status",
            events.ErrorEvent: "error",
        }
        for klass, factory in _every_event_factory(events):
            dumped = factory().model_dump(mode="json")
            assert dumped["kind"] == expected[klass], (
                f"{klass.__name__}: kind slug drift — expected {expected[klass]!r}, got {dumped['kind']!r}"
            )


class TestKindAliasOnInput:
    """The transition validator must accept either discriminator on input."""

    def test_kind_alone_validates_as_type(self, events) -> None:
        # Inbound frame uses ``kind`` only — the validator normalises to
        # the ``type`` literal so the existing Literal discriminator on
        # the subclass still pins the right variant.
        conv_id = uuid.uuid4()
        ev = events.ConversationCreated.model_validate(
            {"kind": "conversation_created", "conversation_id": str(conv_id)}
        )
        assert ev.conversation_id == conv_id

    def test_type_alone_still_validates(self, events) -> None:
        # Legacy clients keep working: ``type`` alone is still the input
        # discriminator.
        conv_id = uuid.uuid4()
        ev = events.ConversationCreated.model_validate(
            {"type": "conversation_created", "conversation_id": str(conv_id)}
        )
        assert ev.conversation_id == conv_id

    def test_both_keys_validate_when_consistent(self, events) -> None:
        # Frames in flight may carry both (the serializer emits both); the
        # validator must accept them.
        conv_id = uuid.uuid4()
        ev = events.ConversationCreated.model_validate(
            {
                "type": "conversation_created",
                "kind": "conversation_created",
                "conversation_id": str(conv_id),
            }
        )
        assert ev.conversation_id == conv_id


class TestRoundTrip:
    """A frame emitted by the serializer must validate back through the model."""

    def test_round_trip_through_dump_and_validate(self, events) -> None:
        for klass, factory in _every_event_factory(events):
            ev = factory()
            wire = ev.model_dump(mode="json")
            # Drop the legacy field — emulating a new client speaking
            # only ``kind`` — and re-validate.
            wire_kind_only = {k: v for k, v in wire.items() if k != "type"}
            klass.model_validate(wire_kind_only)
            # And the inverse — legacy client speaking only ``type``.
            wire_type_only = {k: v for k, v in wire.items() if k != "kind"}
            klass.model_validate(wire_type_only)
