"""Behaviour tests for ``forge_core.security.require_service`` (S2S authz)."""

from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from forge_core.security import require_service
from forge_core.security.identity import IdentityContext


def _req(identity: IdentityContext | None = None, auth_error: object = None) -> object:
    state = types.SimpleNamespace(identity=identity, auth_error=auth_error)
    return types.SimpleNamespace(state=state)


def _ident(
    *, caller: str = "svc-catalog", target: str = "svc-orders", scopes=frozenset({"orders:read"})
) -> IdentityContext:
    return IdentityContext(
        tenant_id="t1",
        subject=caller,
        scopes=scopes,
        raw_claims={"azp": caller, "platform_target_service": target},
    )


async def test_success_returns_identity() -> None:
    dep = require_service(
        target_service="svc-orders",
        allowed_callers=("svc-catalog",),
        required_scope="orders:read",
    )
    ident = _ident()
    assert await dep(_req(ident)) is ident


async def test_forbidden_caller_not_in_allowlist() -> None:
    dep = require_service(target_service="svc-orders", allowed_callers=("svc-catalog",))
    with pytest.raises(HTTPException) as e:
        await dep(_req(_ident(caller="svc-evil")))
    assert e.value.status_code == 403
    assert e.value.detail["reason"] == "forbidden_caller"


async def test_missing_caller_claim_rejected() -> None:
    dep = require_service(target_service="svc-orders", allowed_callers=("svc-catalog",))
    ident = IdentityContext(
        tenant_id="t", subject="x", raw_claims={"platform_target_service": "svc-orders"}
    )
    with pytest.raises(HTTPException) as e:
        await dep(_req(ident))
    assert e.value.status_code == 403
    assert e.value.detail["reason"] == "forbidden_caller"


async def test_audience_mismatch_rejected() -> None:
    dep = require_service(target_service="svc-orders", allowed_callers=("svc-catalog",))
    with pytest.raises(HTTPException) as e:
        await dep(_req(_ident(target="svc-other")))
    assert e.value.detail["reason"] == "audience_mismatch"


async def test_required_scope_enforced() -> None:
    dep = require_service(
        target_service="svc-orders",
        allowed_callers=("svc-catalog",),
        required_scope="orders:write",
    )
    with pytest.raises(HTTPException) as e:
        await dep(_req(_ident(scopes=frozenset({"orders:read"}))))
    assert e.value.detail["reason"] == "scope_required"


async def test_not_authenticated_is_401() -> None:
    dep = require_service(target_service="svc-orders", allowed_callers=("svc-catalog",))
    with pytest.raises(HTTPException) as e:
        await dep(_req(identity=None))
    assert e.value.status_code == 401


def test_empty_allowlist_is_a_build_error() -> None:
    with pytest.raises(ValueError):
        require_service(target_service="svc-orders", allowed_callers=())
