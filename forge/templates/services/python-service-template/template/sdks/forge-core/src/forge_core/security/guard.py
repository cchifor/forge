"""AuthGuard — the JWT bearer-token verifier.

This is the integration piece the security layer orbits. On each token:

1. Reject any algorithm not in the configured allowlist (defends against
   ``alg: none`` and symmetric-algorithm confusion).
2. Read the unverified ``iss`` and ``kid`` headers, fetch the matching JWK
   via :class:`JWKSCache`.
3. Verify signature, ``aud``, ``exp``, ``nbf``, and required-claim presence
   via PyJWT.
4. Resolve the tenant claim and consult the :class:`IssuerTrustMap`: reject
   tokens whose ``iss`` does not match the tenant's expected issuer, or whose
   tenant is suspended.
5. Build :class:`IdentityContext` and return.

A failure at any step raises a typed :class:`AuthError`; the caller's HTTP
exception-handler translates these into RFC 7807 problem responses.

This is the *generic*, Strive-decoupled verifier: the tenant id is a plain
string (no UUID requirement), the claim names are fully configurable, and the
signing algorithm defaults to ES256 but is overridable (RS256 / ES384 / …).
It carries no on-behalf-of (RFC 8693 ``act``) chain handling or revocation
store — those richer features live in the optional platform-auth SDK shipped
at ``auth.mode=generate``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import jwt as pyjwt
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
)

from forge_core.security.exceptions import (
    InvalidToken,
    IssuerNotTrusted,
    TenantSuspended,
    TokenExpired,
)
from forge_core.security.identity import IdentityContext
from forge_core.security.jwks import JWKSCache
from forge_core.security.trust import IssuerTrustMap

_log = logging.getLogger(__name__)

DEFAULT_TENANT_ID_CLAIM = "https://forge/tenant_id"
DEFAULT_TENANT_SLUG_CLAIM = "https://forge/tenant_slug"
DEFAULT_ROLES_CLAIM = "roles"
DEFAULT_SCOPE_CLAIM = "scope"

REQUIRED_CLAIMS: tuple[str, ...] = ("iss", "aud", "sub", "exp", "iat", "jti")
"""Claims PyJWT must enforce as present (RFC 9068 §2.2). ``nbf`` is optional
per RFC 7519 §4.1.5; PyJWT still verifies it when present."""

DEFAULT_ALGORITHMS: tuple[str, ...] = ("ES256",)
"""Accepted JWT signing algorithms. Asymmetric only — never ``none`` or
``HS*``. ES256 (ECDSA P-256) is the default; callers verifying RS256 tokens
(e.g. Keycloak-issued bearers) pass ``algorithms=("RS256",)`` explicitly."""

DEFAULT_CLOCK_SKEW_SECONDS = 30


class AuthGuard:
    """JWT bearer-token verifier."""

    def __init__(
        self,
        *,
        audience: str,
        jwks: JWKSCache,
        trust_map: IssuerTrustMap | None = None,
        algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS,
        clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
        tenant_id_claim: str = DEFAULT_TENANT_ID_CLAIM,
        tenant_slug_claim: str = DEFAULT_TENANT_SLUG_CLAIM,
        roles_claim: str = DEFAULT_ROLES_CLAIM,
        scope_claim: str = DEFAULT_SCOPE_CLAIM,
    ) -> None:
        if not audience:
            raise ValueError("audience must be non-empty")
        if not algorithms:
            raise ValueError("algorithms must be non-empty")
        for alg in algorithms:
            if alg.lower() == "none":
                raise ValueError(f"algorithm {alg!r} is forbidden")
        if clock_skew_seconds < 0:
            raise ValueError("clock_skew_seconds must be non-negative")

        self._audience = audience
        self._jwks = jwks
        self._trust_map = trust_map
        self._algorithms = tuple(algorithms)
        self._clock_skew = clock_skew_seconds
        self._tenant_id_claim = tenant_id_claim
        self._tenant_slug_claim = tenant_slug_claim
        self._roles_claim = roles_claim
        self._scope_claim = scope_claim

    @property
    def audience(self) -> str:
        return self._audience

    async def verify(self, token: str) -> IdentityContext:
        """Validate ``token`` and return the verified :class:`IdentityContext`."""
        if not token:
            raise InvalidToken("missing bearer token")

        unverified_header = self._unverified_header(token)
        alg = unverified_header.get("alg")
        if not isinstance(alg, str) or alg not in self._algorithms:
            raise InvalidToken(f"algorithm {alg!r} not allowed")
        kid = unverified_header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise InvalidToken("token header missing 'kid'")

        unverified_claims = self._unverified_claims(token)
        iss = unverified_claims.get("iss")
        if not isinstance(iss, str) or not iss:
            raise InvalidToken("token missing 'iss'")
        if iss not in self._jwks.registered_issuers():
            raise InvalidToken(f"issuer {iss!r} is not registered")

        try:
            jwk = await self._jwks.get_signing_key(iss, kid)
        except InvalidToken:
            raise
        except KeyError as exc:
            raise InvalidToken("issuer not registered") from exc

        try:
            claims = pyjwt.decode(
                token,
                key=jwk.key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                leeway=self._clock_skew,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except ExpiredSignatureError as exc:
            raise TokenExpired("token expired") from exc
        except ImmatureSignatureError as exc:
            raise InvalidToken("token not yet valid (nbf in future)") from exc
        except InvalidAudienceError as exc:
            raise InvalidToken(f"audience mismatch (expected {self._audience!r})") from exc
        except InvalidIssuerError as exc:
            raise InvalidToken("issuer mismatch") from exc
        except InvalidSignatureError as exc:
            raise InvalidToken("signature mismatch") from exc
        except MissingRequiredClaimError as exc:
            raise InvalidToken(f"missing required claim: {exc.claim}") from exc
        except DecodeError as exc:
            raise InvalidToken("malformed token") from exc
        except InvalidTokenError as exc:
            raise InvalidToken(str(exc) or "invalid token") from exc

        tenant_id = self._extract_tenant_id(claims)
        if self._trust_map is not None:
            await self._enforce_trust(tenant_id, iss)

        slug_raw = claims.get(self._tenant_slug_claim)
        tenant_slug = slug_raw if isinstance(slug_raw, str) else None

        return IdentityContext(
            tenant_id=tenant_id,
            subject=claims["sub"],
            roles=self._roles(claims),
            scopes=self._scopes(claims),
            tenant_slug=tenant_slug,
            raw_claims=claims,
        )

    # ------------------------------------------------------------------ helpers

    def _unverified_header(self, token: str) -> dict[str, Any]:
        try:
            return pyjwt.get_unverified_header(token)
        except DecodeError as exc:
            raise InvalidToken("malformed token header") from exc
        except InvalidTokenError as exc:
            raise InvalidToken(f"unable to read token header: {exc}") from exc

    def _unverified_claims(self, token: str) -> dict[str, Any]:
        try:
            return pyjwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_iss": False,
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
        except DecodeError as exc:
            raise InvalidToken("malformed token") from exc
        except InvalidTokenError as exc:
            raise InvalidToken(f"unable to read token: {exc}") from exc

    def _extract_tenant_id(self, claims: Mapping[str, Any]) -> str:
        raw = claims.get(self._tenant_id_claim)
        if raw is None:
            raise InvalidToken(f"missing tenant claim: {self._tenant_id_claim!r}")
        if not isinstance(raw, str) or not raw:
            raise InvalidToken(f"tenant claim {self._tenant_id_claim!r} must be a non-empty string")
        return raw

    async def _enforce_trust(self, tenant_id: str, iss: str) -> None:
        assert self._trust_map is not None  # narrowed by caller
        record = await self._trust_map.get(tenant_id)
        # An empty/permissive trust map (no record) accepts any tenant — the
        # single-issuer default. Records are only enforced when present.
        if record is None:
            return
        if record.expected_issuer != iss:
            raise IssuerNotTrusted(
                f"tenant {tenant_id} expects issuer {record.expected_issuer!r}, "
                f"token presents {iss!r}"
            )
        if record.suspended:
            raise TenantSuspended(f"tenant {tenant_id} is suspended")

    def _roles(self, claims: Mapping[str, Any]) -> frozenset[str]:
        raw = claims.get(self._roles_claim)
        if raw is None:
            return frozenset()
        if isinstance(raw, str):
            tokens = [r.strip() for r in raw.replace(",", " ").split() if r.strip()]
            return frozenset(tokens)
        if isinstance(raw, list):
            return frozenset(str(r) for r in raw if isinstance(r, str))
        raise InvalidToken(f"roles claim {self._roles_claim!r} has unexpected shape")

    def _scopes(self, claims: Mapping[str, Any]) -> frozenset[str]:
        raw = claims.get(self._scope_claim)
        if raw is None:
            return frozenset()
        if isinstance(raw, str):
            return frozenset(s for s in raw.split() if s)
        if isinstance(raw, list):
            return frozenset(str(s) for s in raw if isinstance(s, str))
        raise InvalidToken(f"scope claim {self._scope_claim!r} has unexpected shape")


__all__ = [
    "DEFAULT_ALGORITHMS",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "DEFAULT_ROLES_CLAIM",
    "DEFAULT_SCOPE_CLAIM",
    "DEFAULT_TENANT_ID_CLAIM",
    "DEFAULT_TENANT_SLUG_CLAIM",
    "REQUIRED_CLAIMS",
    "AuthGuard",
]
