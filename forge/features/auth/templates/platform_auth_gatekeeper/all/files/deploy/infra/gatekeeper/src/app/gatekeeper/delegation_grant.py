# src/app/gatekeeper/delegation_grant.py
"""Long-lived delegation grants for async workflow runs (WS3-delegated-user-async).

A workflow run started by user U at T0 may execute steps minutes or
hours later — long after U's 5-minute internal JWT has expired.
Token-exchange refuses an expired ``subject_token`` by design, so the
worker can't directly mint a delegated user token at step time.

This module solves that without storing refresh tokens in the worker.
At run start the worker calls :func:`POST /auth/delegation-grant` with
its S2S credential **and** the user's still-valid internal JWT;
gatekeeper extracts the user identity, encrypts it under a key it
controls, and returns an opaque grant id with a configurable TTL
(default 1 hour, max 24h).

At step time the worker calls :func:`POST /auth/delegation-exchange`
with its S2S credential **and** the grant id. Gatekeeper validates the
grant is unexpired and not revoked, decrypts the user identity, and
mints a fresh internal JWT preserving the user's ``sub`` and
``tenant_id`` plus an ``act`` chain naming the calling service.

Lifecycle
---------

* **Issue**  — record persists in Redis at ``gk:delegation_grant:<grant_id>``;
  TTL = the requested TTL (capped at 24h). Encrypted with a stable
  Fernet key sourced from ``DELEGATION_GRANT_FERNET_KEY``.
* **Revoke** — explicit ``DELETE /auth/delegation-grant/<id>`` (operator)
  or natural expiry. Revocation latency = step polling cadence.
* **Audit**  — every issue/exchange/revoke logs grant_id + caller
  client_id + user sub. The grant id is shown to operators in run UI
  so they can correlate "this run's identity grant" to specific actions.

Security properties
-------------------

* Operators set the Fernet key via SOPS-encrypted env (one rotation
  per N months); a key rotation invalidates all outstanding grants.
* The grant body is opaque to the worker — only gatekeeper can
  decrypt it. A leaked grant id is useful only as a credential to
  call ``/auth/delegation-exchange``, which still requires the
  client_id+secret combo. Stolen client_secret + leaked grant id is
  the worst case; the grant TTL bounds blast radius.
* Token-exchange's ``act`` chain still records the calling service;
  audits on the downstream backend show "user did X, via svc-workflow".
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


DEFAULT_GRANT_TTL_SECONDS = 3600  # 1 hour
MAX_GRANT_TTL_SECONDS = 86400  # 24 hours


class DelegationGrantError(RuntimeError):
    """Base class for grant-related failures.

    ``error_code`` is the OAuth2 ``error`` enum value that should appear
    in the endpoint response. Defaults to ``invalid_grant`` so
    forgetting to pass the field still produces a sensible 4xx.
    """

    def __init__(self, message: str, *, error_code: str = "invalid_grant") -> None:
        super().__init__(message)
        self.error_code = error_code


def _key_for(grant_id: str) -> str:
    return f"gk:delegation_grant:{grant_id}"


class DelegationGrantStore:
    """Redis-backed encrypted store for delegation grants.

    Each grant carries a copy of the user identity claims (sub, tenant,
    email, scope) — enough to mint a delegated internal JWT later
    without consulting Keycloak again. The plaintext is encrypted with
    a server-controlled Fernet key so an operator with read-only Redis
    access can't reconstruct user identity from grant rows.
    """

    __slots__ = ("_redis", "_fernet")

    def __init__(self, redis: Any, fernet: Fernet) -> None:
        self._redis = redis
        self._fernet = fernet

    async def issue(
        self,
        *,
        identity: dict[str, Any],
        ttl_seconds: int,
    ) -> tuple[str, int]:
        """Persist a new grant. Returns ``(grant_id, expires_at_unix)``.

        ``identity`` is the dict of claims to preserve at exchange time
        — at minimum ``sub`` and ``tenant_id``. Extras (email, roles)
        are copied through if present.
        """
        if ttl_seconds <= 0:
            raise DelegationGrantError("ttl_seconds must be positive")
        ttl_seconds = min(ttl_seconds, MAX_GRANT_TTL_SECONDS)

        grant_id = secrets.token_urlsafe(24)
        now = int(time.time())
        envelope = {
            "issued_at": now,
            "expires_at": now + ttl_seconds,
            "identity": identity,
        }
        ciphertext = self._fernet.encrypt(json.dumps(envelope).encode("utf-8"))
        await self._redis.setex(_key_for(grant_id), ttl_seconds, ciphertext)
        logger.info(
            "delegation_grant_issued grant=%s sub=%s tenant=%s ttl=%ds",
            grant_id,
            identity.get("sub"),
            identity.get("https://forge/tenant_id") or identity.get("tenant_id"),
            ttl_seconds,
        )
        return grant_id, envelope["expires_at"]

    async def redeem(self, grant_id: str) -> dict[str, Any]:
        """Look up + decrypt the grant. Returns the stored ``identity`` dict.

        Raises :class:`DelegationGrantError` for missing / expired /
        tampered records. Does NOT delete the grant — the same grant
        can be redeemed many times until natural TTL expiry, supporting
        multi-step runs.
        """
        ciphertext = await self._redis.get(_key_for(grant_id))
        if ciphertext is None:
            raise DelegationGrantError("grant not found or expired")
        try:
            plaintext = self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise DelegationGrantError(
                "grant ciphertext invalid (key rotated?)",
            ) from exc
        try:
            envelope = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DelegationGrantError("grant body malformed") from exc

        # Defense in depth — the Redis TTL already enforces this, but
        # if the key was extended out-of-band the envelope's own
        # ``expires_at`` is the source of truth.
        if int(envelope.get("expires_at", 0)) <= int(time.time()):
            raise DelegationGrantError("grant expired")
        identity = envelope.get("identity")
        if not isinstance(identity, dict) or "sub" not in identity:
            raise DelegationGrantError("grant identity malformed")
        return identity

    async def revoke(self, grant_id: str) -> bool:
        """Delete the grant. Returns ``True`` if the row existed."""
        deleted = await self._redis.delete(_key_for(grant_id))
        if deleted:
            logger.info("delegation_grant_revoked grant=%s", grant_id)
        return bool(deleted)


__all__ = [
    "DEFAULT_GRANT_TTL_SECONDS",
    "MAX_GRANT_TTL_SECONDS",
    "DelegationGrantError",
    "DelegationGrantStore",
]
