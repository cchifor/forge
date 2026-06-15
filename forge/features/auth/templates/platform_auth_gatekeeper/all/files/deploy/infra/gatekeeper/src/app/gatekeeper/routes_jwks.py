# src/app/gatekeeper/routes_jwks.py
"""``GET /auth/jwks`` — public JWK Set for gatekeeper-minted internal JWTs.

Each backend fetches this URL once at startup and again every JWKS cache
lifespan (``platform_auth.JWKSCache``: default 600 s) to refresh the
keys it uses to verify gatekeeper-issued bearer tokens.

The endpoint:

* Has **no auth dependency**. Public keys are public.
* Sets ``Cache-Control: public, max-age=300`` so reverse proxies and
  backends share the response.
* Sets ``ETag`` to the SHA-256 of the JSON body, enabling
  ``If-None-Match`` conditional GETs that return 304 without a payload.
* Returns 503 when the application has not yet initialised a KeyRing
  (defensive — startup ordering should guarantee initialisation).
"""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)


router = APIRouter(tags=["gatekeeper-jwks"])


@router.get("/auth/jwks", include_in_schema=False)
async def auth_jwks(request: Request) -> Response:
    key_ring = getattr(request.app.state, "key_ring", None)
    if key_ring is None:
        return Response(
            status_code=503,
            content="gatekeeper key ring unavailable",
            media_type="text/plain",
        )

    body = json.dumps(
        key_ring.public_jwks(),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    etag = '"' + hashlib.sha256(body).hexdigest() + '"'

    cache_headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=300",
    }

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cache_headers)

    return Response(
        content=body,
        media_type="application/json",
        headers=cache_headers,
    )
