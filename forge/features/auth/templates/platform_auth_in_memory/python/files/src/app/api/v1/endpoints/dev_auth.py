"""Dev-only token endpoint for the ``in_memory`` auth provider.

Exposes two unauthenticated routes under ``/dev/auth`` that exist ONLY so a
developer can drive the authenticated surface of the service without standing
up Keycloak / Gatekeeper:

* ``POST /dev/auth/token`` — mint a signed ES256 dev token for an arbitrary
  ``sub`` / ``scopes`` / ``tenant_id``.
* ``GET  /dev/auth/jwks``  — serve the issuer's JWKS (handy for debugging /
  pointing external tooling at the in-process issuer).

These routes are generated only when ``auth.provider=in_memory`` and that
provider is refused on a production posture, so they never ship to prod.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.security.in_memory_auth import get_issuer

router = APIRouter()


class DevTokenRequest(BaseModel):
    """Body for ``POST /dev/auth/token``."""

    sub: str = Field(..., description="Subject (user / service identifier).")
    scopes: list[str] = Field(default_factory=list, description="Granted scopes.")
    tenant_id: str | None = Field(
        default=None, description="Tenant UUID; defaults to the dev tenant."
    )
    roles: list[str] = Field(default_factory=list, description="Realm roles.")
    expires_in: int = Field(
        default=3600, ge=1, le=86400, description="Token lifetime in seconds."
    )


class DevTokenResponse(BaseModel):
    """Response for ``POST /dev/auth/token``."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int


@router.post("/token", response_model=DevTokenResponse)
async def mint_dev_token(body: DevTokenRequest, request: Request) -> DevTokenResponse:
    """Mint a signed dev token. UNAUTHENTICATED — dev provider only."""
    issuer = get_issuer(request.app)
    from app.security.in_memory_issuer import DEV_TENANT_ID

    token = issuer.mint(
        sub=body.sub,
        scopes=body.scopes,
        tenant_id=body.tenant_id or DEV_TENANT_ID,
        roles=body.roles,
        exp_seconds=body.expires_in,
    )
    return DevTokenResponse(access_token=token, expires_in=body.expires_in)


@router.get("/jwks")
async def dev_jwks(request: Request) -> dict[str, Any]:
    """Serve the in-process issuer's JWKS document."""
    return get_issuer(request.app).jwks_document()
