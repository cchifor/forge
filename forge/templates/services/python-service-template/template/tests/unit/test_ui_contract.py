"""Wire contracts stay round-trippable when generated schemas are upgraded."""

import pytest
from pydantic import ValidationError

from app.domain.canvas_events import AgUiEventAdapter
from app.domain.canvas_props import (
    CodeViewerProps,
    DataTableProps,
    DynamicFormProps,
    ReportProps,
    WorkflowDiagramProps,
)


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("ag-ui-payload", {"engine": "ag-ui", "component_name": "Report", "props": {}}),
        ("agent-state", {"model": "example", "custom_extension": {"status": "ready"}}),
        ("hitl-response", {"tool_call_id": "call-1", "answer": "approved"}),
        ("mcp-ext-payload", {"engine": "mcp-ext", "html": "<p>Result</p>"}),
        ("tool-call-info", {"id": "call-1", "name": "search", "status": "completed"}),
        ("user-prompt-payload", {"tool_call_id": "call-1", "question": "Continue?", "options": []}),
        ("workspace-activity", {"engine": "ag-ui", "activityType": "report", "messageId": "message-1", "content": {}}),
    ],
)
def test_event_wire_round_trip(kind, payload):
    event = AgUiEventAdapter.validate_python({"kind": kind, "payload": payload})
    encoded = AgUiEventAdapter.dump_json(event)
    assert AgUiEventAdapter.validate_json(encoded) == event
    assert event.payload.model_dump(exclude_unset=True) == payload


@pytest.mark.parametrize(
    "event",
    [
        {"kind": "unknown", "payload": {}},
        {"kind": "ag-ui-payload", "payload": {"engine": "untrusted", "component_name": "Report", "props": {}}},
        {"kind": "tool-call-info", "payload": {"id": "1", "name": "tool", "status": "invalid"}},
        {"kind": "hitl-response", "payload": {"answer": "missing correlation id"}},
    ],
)
def test_invalid_wire_payload_is_rejected(event):
    with pytest.raises(ValidationError):
        AgUiEventAdapter.validate_python(event)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (CodeViewerProps, {"code": "print('hello')", "language": "python"}),
        (DataTableProps, {"columns": [{"key": "name"}], "rows": [{"name": "first"}]}),
        (DynamicFormProps, {"fields": [{"name": "email", "type": "string"}]}),
        (ReportProps, {"markdown": "# Report"}),
        (WorkflowDiagramProps, {"nodes": [{"id": "start"}], "edges": []}),
    ],
)
def test_canvas_props_preserve_public_payloads(model, payload):
    value = model.model_validate(payload)
    assert model.model_validate_json(value.model_dump_json()) == value
    assert value.model_dump(exclude_unset=True) == payload
    with pytest.raises(ValidationError):
        model.model_validate({})
