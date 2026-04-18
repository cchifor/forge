"""Fragment smoke tests for `admin_panel`.

Covers the A1.3 tenant-scoping invariants: missing headers produce a
"no rows" filter (fail closed), and `mode=all` refuses to mount without
an explicit acknowledgement.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI

from app.admin import _build_tenant_scoped_base, _tenant_id_from_request, mount_admin


class _FakeReq:
    def __init__(self, headers: dict) -> None:
        self.headers = headers


def test_tenant_id_parses_customer_header() -> None:
    cid = uuid.uuid4()
    req = _FakeReq({"x-gatekeeper-customer-id": str(cid)})
    assert _tenant_id_from_request(req) == cid


def test_tenant_id_falls_back_to_user_id_header() -> None:
    cid = uuid.uuid4()
    req = _FakeReq({"x-gatekeeper-user-id": str(cid)})
    assert _tenant_id_from_request(req) == cid


def test_tenant_id_returns_none_without_headers() -> None:
    assert _tenant_id_from_request(_FakeReq({})) is None


def test_tenant_id_rejects_invalid_uuid() -> None:
    assert _tenant_id_from_request(_FakeReq({"x-customer-id": "not-a-uuid"})) is None


def test_tenant_scoped_model_view_builds() -> None:
    Scoped, ModelView = _build_tenant_scoped_base()
    assert Scoped is not None
    assert ModelView is not None
    assert getattr(Scoped, "tenant_scoped", None) is True


def test_mode_all_refuses_without_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PANEL_MODE", "all")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ADMIN_PANEL_AUTH_ACKNOWLEDGED", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    app = FastAPI()
    mount_admin(app)
    admin_routes = [r for r in app.routes if "/admin" in getattr(r, "path", "")]
    assert not admin_routes, "mode=all without ACK must not mount"


def test_mode_disabled_is_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_PANEL_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    app = FastAPI()
    mount_admin(app)
    admin_routes = [r for r in app.routes if "/admin" in getattr(r, "path", "")]
    assert not admin_routes
