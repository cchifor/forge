"""CloudEvents v1.0 envelope (vendored, framework-agnostic).

Spec: https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md

The *structured* JSON wire format is used — the entire envelope is one
JSON object. Required attributes are ``id``, ``source``,
``specversion``, ``type``. Optional standard attributes are ``time``,
``subject``, ``datacontenttype``, ``data``.

Two optional extension attributes carry multi-tenant / actor context
when the service runs inside a tenant-aware platform: ``tenantid`` and
``actorid``. Both are OPTIONAL — a single-tenant service simply leaves
them unset. CloudEvents requires extension names to be alphanumeric
lowercase (no underscores, no dots), hence ``tenantid`` not
``tenant_id``. ``traceparent`` carries W3C Trace Context across the bus;
it is filled in by :func:`app.events.otel.inject_traceparent` at publish
time when OpenTelemetry is installed.

This module imports only the stdlib + pydantic — no private SDKs.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Postgres ``NOTIFY`` payload limit is 8000 bytes. We reserve ~1KB
# headroom so a single added field on the next deploy can't silently
# push a payload over the wire limit in production.
MAX_ENVELOPE_BYTES = 7000


class CloudEvent(BaseModel):
    """A CloudEvents v1.0 envelope.

    Frozen and ``extra="forbid"``: the schema is the contract between
    every producer and every consumer that shares the bus.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    specversion: str = "1.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    type: str
    subject: str | None = None
    time: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.UTC))
    datacontenttype: str = "application/json"
    data: dict[str, Any] = Field(default_factory=dict)

    # Optional platform extensions. Unset in single-tenant services.
    tenantid: str | None = None
    actorid: str | None = None
    traceparent: str | None = None

    @field_validator("specversion")
    @classmethod
    def _supported_specversion(cls, v: str) -> str:
        if v != "1.0":
            raise ValueError(f"Unsupported CloudEvents specversion: {v}")
        return v

    def to_json(self) -> str:
        """Serialize to JSON.

        Raises ``ValueError`` if the result is too large for the wire
        transport (Postgres ``NOTIFY`` 8KB cap).
        """
        payload = self.model_dump_json()
        size = len(payload.encode("utf-8"))
        if size > MAX_ENVELOPE_BYTES:
            raise ValueError(
                f"CloudEvent {self.type} payload is {size} bytes — "
                f"exceeds the {MAX_ENVELOPE_BYTES}-byte cap. Pare ``data`` "
                f"down to ids + minimal context; clients can re-fetch."
            )
        return payload

    @classmethod
    def from_json(cls, payload: str) -> Self:
        return cls.model_validate_json(payload)
