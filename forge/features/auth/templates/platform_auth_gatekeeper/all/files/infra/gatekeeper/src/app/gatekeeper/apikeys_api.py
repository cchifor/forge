# src/app/gatekeeper/apikeys_api.py
"""
REST API for API key lifecycle management (create, list, revoke).

Tenant + user identity is resolved from the **verified server-side session**
(the ``tenant_session_id`` cookie -> Redis), never from a client-supplied
``X-Gatekeeper-*`` request header. The Gatekeeper is reachable directly
(compose maps ``5000:5000``) and nothing strips inbound identity headers, so a
raw header is spoofable -- trusting it would let any caller mint / list /
revoke API keys for an arbitrary tenant. This mirrors the rest of the platform,
where the legacy plain-header trust path was removed in favour of verified
credentials.
"""

from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gatekeeper.apikeys import (
    generate_api_key,
    key_prefix,
    list_api_keys,
    revoke_api_key,
    store_api_key,
)
from app.gatekeeper.config import get_settings
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


async def _authenticated_identity(request: Request) -> tuple[str, str]:
    """Resolve ``(tenant_id, user_id)`` from the verified server-side session.

    The tenant is read from the Redis-backed session keyed by the
    ``tenant_session_id`` cookie -- never from a client-supplied
    ``X-Gatekeeper-*`` header, which is spoofable on the directly-exposed
    Gatekeeper port. A request without a valid, unexpired session is rejected
    with 401.
    """
    cfg = get_settings()
    session_id = request.cookies.get(cfg.session_id_cookie_name)
    server_session = getattr(request.app.state, "server_session", None)
    if not session_id or server_session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session = await server_session.check_validity(session_id, now=int(time.time()))
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return session.tenant_id, (session.sub or "unknown")


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("", response_model=CreateKeyResponse, status_code=201)
async def create_key(
    body: CreateKeyRequest,
    request: Request,
) -> CreateKeyResponse:
    """Generate a new API key for the authenticated tenant."""
    tenant, owner = await _authenticated_identity(request)

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
    request: Request,
) -> ListKeysResponse:
    """List all active API keys for the authenticated tenant."""
    tenant, _owner = await _authenticated_identity(request)
    records = await list_api_keys(tenant)
    APIKEY_OPERATIONS.labels(tenant_id=tenant, operation="listed").inc()
    return ListKeysResponse(keys=[KeySummary(**r) for r in records])


@router.delete("/{key_hash}")
async def revoke_key(
    key_hash: str,
    request: Request,
) -> RevokeKeyResponse:
    """
    Revoke (delete) an API key by its hash.

    Takes effect immediately — the next ``/auth`` call with this key
    will be rejected.
    """
    tenant, _owner = await _authenticated_identity(request)
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
