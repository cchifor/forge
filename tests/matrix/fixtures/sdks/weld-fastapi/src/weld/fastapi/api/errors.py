"""``weld.fastapi.api.errors.Error`` — RFC-007 error envelope (matrix-CI stub).

The template's ``app.core.errors._envelope`` builds an ``Error`` with
``message``, ``type``, and a ``detail`` dict containing ``code`` /
``correlation_id`` plus exception-specific fields. The test suite
expects the serialized body to be::

    {"error": {
        "message": ..., "type": ...,
        "code": ..., "correlation_id": ...,
        "context": {...}     # remaining detail fields
    }}

This stub's ``model_dump`` reshapes the stored detail into that envelope
so the template's tests pass against the stub. Real weld-fastapi does
the equivalent (possibly via a different field layout) — matrix CI
needs the same observable contract.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Error(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str = ""
    type: str = ""
    detail: dict[str, Any] | None = None

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        detail_copy: dict[str, Any] = dict(self.detail or {})
        code = detail_copy.pop("code", "")
        correlation_id = detail_copy.pop("correlation_id", "")
        return {
            "error": {
                "message": self.message,
                "type": self.type,
                "code": code,
                "correlation_id": correlation_id,
                "context": detail_copy,
            }
        }
