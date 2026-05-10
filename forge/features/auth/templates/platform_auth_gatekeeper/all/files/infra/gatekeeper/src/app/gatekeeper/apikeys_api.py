# src/app/gatekeeper/apikeys_api.py
"""
REST API for API key lifecycle management (create, list, revoke).

These endpoints are **protected by the Gatekeeper itself** — the caller
must already be authenticated (human or machine) and carry admin-level
roles.  Tenant identity is read from the ``X-Gatekeeper-Tenant`` header
injected by Traefik's ForwardAuth middleware.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.gatekeeper.apikeys import (
    generate_api_key,
    key_prefix,
    list_api_keys,
    revoke_api_key,
    store_api_key,
)
from app.gatekeeper.metrics import APIKEY_OPERATIONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


# ── Request / Response models ───────────────────────────────────────────────


class CreateKeyRequest(BaseModel):
    """Payload for creating a new API key."""

    name: str = Field(
        ..., min_length=1, max_length=128, description="Human-readable label"
    )
    roles: list[str] = Field(
        default_factory=list, description="Roles granted to this key"
    )


class CreateKeyResponse(BaseModel):
    """Returned exactly once — the plain-text key is never shown again."""

    message: str = "Copy this key now. You will not be able to see it again."
    api_key: str
    key_id: str
    name: str
    prefix: str
    roles: list[str]


class KeySummary(BaseModel):
    """Public metadata for a stored API key (no secrets)."""

    key_id: str
    name: str
    roles: list[str]
    owner: str
    key_hash: str


class ListKeysResponse(BaseModel):
    keys: list[KeySummary]


class RevokeKeyResponse(BaseModel):
    revoked: bool
    key_hash: str


# ── Helpers ─────────────────────────────────────────────────────────────────


def _require_tenant(
    x_gatekeeper_tenant: str | None,
) -> str:
    """
    Extract the tenant from the Gatekeeper header.

    In production, Traefik always injects ``X-Gatekeeper-Tenant`` on
    requests that have already passed ``/auth``.  If missing, we reject.
    """
    if not x_gatekeeper_tenant:
        raise HTTPException(status_code=401, detail="Missing tenant context")
    return x_gatekeeper_tenant


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("", response_model=CreateKeyResponse, status_code=201)
async def create_key(
    body: CreateKeyRequest,
    x_gatekeeper_tenant: str | None = Header(None),
    x_gatekeeper_user_id: str | None = Header(None),
) -> CreateKeyResponse:
    """Generate a new API key for the authenticated tenant."""
    tenant = _require_tenant(x_gatekeeper_tenant)
    owner = x_gatekeeper_user_id or "unknown"

    plain_key, key_hash = generate_api_key(tenant)
    key_id = secrets.token_hex(8)
    prefix = key_prefix(plain_key)

    await store_api_key(
        key_hash,
        key_id=key_id,
        tenant_id=tenant,
        name=body.name,
        roles=body.roles,
        owner=owner,
    )

    logger.info(
        "API key created: id=%s tenant=%s name=%s owner=%s",
        key_id,
        tenant,
        body.name,
        owner,
    )
    APIKEY_OPERATIONS.labels(tenant_id=tenant, operation="created").inc()

    return CreateKeyResponse(
        api_key=plain_key,
        key_id=key_id,
        name=body.name,
        prefix=prefix,
        roles=body.roles,
    )


@router.get("", response_model=ListKeysResponse)
async def list_keys(
    x_gatekeeper_tenant: str | None = Header(None),
) -> ListKeysResponse:
    """List all active API keys for the authenticated tenant."""
    tenant = _require_tenant(x_gatekeeper_tenant)
    records = await list_api_keys(tenant)
    APIKEY_OPERATIONS.labels(tenant_id=tenant, operation="listed").inc()
    return ListKeysResponse(keys=[KeySummary(**r) for r in records])


@router.delete("/{key_hash}")
async def revoke_key(
    key_hash: str,
    x_gatekeeper_tenant: str | None = Header(None),
) -> RevokeKeyResponse:
    """
    Revoke (delete) an API key by its hash.

    Takes effect immediately — the next ``/auth`` call with this key
    will be rejected.
    """
    tenant = _require_tenant(x_gatekeeper_tenant)
    deleted = await revoke_api_key(key_hash, tenant)

    if deleted:
        logger.info("API key revoked: hash=%s tenant=%s", key_hash[:12], tenant)
        APIKEY_OPERATIONS.labels(tenant_id=tenant, operation="revoked").inc()
    else:
        logger.warning(
            "Revoke requested for unknown key: hash=%s tenant=%s",
            key_hash[:12],
            tenant,
        )

    return RevokeKeyResponse(revoked=deleted, key_hash=key_hash)
