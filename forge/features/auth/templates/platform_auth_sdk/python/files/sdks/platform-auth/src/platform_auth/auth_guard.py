"""AuthGuard — the FastAPI dependency that validates incoming bearer tokens.

This is the integration piece every other module orbits. On each request:

1. Extract ``Authorization: Bearer <jwt>`` from the request.
2. Reject any algorithm not in the configured allowlist (defends against
   ``alg: none`` and symmetric-algorithm confusion).
3. Read the unverified ``iss`` and ``kid`` headers, fetch the matching JWK
   via :class:`JWKSCache`.
4. Verify signature, ``aud``, ``exp``, ``nbf``, and required-claim presence
   via PyJWT.
5. Resolve the tenant claim and consult the :class:`IssuerTrustMap`:
   reject tokens whose ``iss`` does not match the tenant's expected issuer
   (:class:`IssuerNotTrusted`), or whose tenant is suspended
   (:class:`TenantSuspended`).
6. Consult the :class:`RevocationStore` (if wired); reject revoked ``jti``.
7. Walk the ``act`` chain (RFC 8693) and ask :class:`MayActPolicy` to
   authorize each actor against the destination audience.
8. Build :class:`IdentityContext`, attach to ``request.state.identity``,
   return.

A failure at any step raises a typed :class:`AuthError`. The caller's HTTP
exception-handler is expected to translate these into RFC 7807 problem
responses.

The verifier is intended to be constructed once per process and reused as a
FastAPI dependency::

    auth_guard = AuthGuard(audience="svc-knowledge", jwks=jwks_cache, ...)

    @app.get("/items")
    async def list_items(identity: IdentityContext = Depends(auth_guard)):
        ...

It is also valid as a ``Starlette`` middleware via the convenience
:meth:`as_middleware` shim.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

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

from platform_auth.exceptions import (
    ActorNotAuthorized,
    InvalidToken,
    IssuerNotTrusted,
    ScopeRequired,
    TenantSuspended,
    TokenExpired,
    TokenRevoked,
)
from platform_auth.identity import IdentityContext
from platform_auth.jwks import JWKSCache
from platform_auth.may_act import MayActPolicy
from platform_auth.revocation import RevocationStore
from platform_auth.trust import IssuerTrustMap

_log = logging.getLogger(__name__)

DEFAULT_TENANT_ID_CLAIM = "https://platform/tenant_id"
DEFAULT_TENANT_SLUG_CLAIM = "https://platform/tenant_slug"
DEFAULT_ROLES_CLAIM = "roles"
DEFAULT_SCOPE_CLAIM = "scope"

REQUIRED_CLAIMS: tuple[str, ...] = ("iss", "aud", "sub", "exp", "iat", "jti")
"""Claims PyJWT must enforce as present (RFC 9068 §2.2 — Required Claims).
``nbf`` is intentionally absent: it is OPTIONAL per RFC 7519 §4.1.5 and
RFC 9068 does not list it as required. Keycloak (and most IdPs) omit it
by default. PyJWT still verifies ``nbf`` if a token presents one, just
doesn't fail when it is missing. The tenant claim is checked separately
so we can produce a clearer error message."""

DEFAULT_ALGORITHMS: tuple[str, ...] = ("ES256",)
"""Accepted JWT signing algorithms. Asymmetric only — never include
``none`` or ``HS*`` here; doing so would let any party with the
secret-vs-public-key mix-up forge tokens.

Phase 4 default. The platform standardised on ECDSA P-256 (ES256) for
gatekeeper-minted internal JWTs in Phase 0 (smaller signatures,
~10x faster signing than RS256, first-class AWS KMS support). Callers
that consume RS256 tokens directly — e.g. anything still verifying
Keycloak-issued bearers, or test fixtures using
:class:`platform_auth.testing.TestRSAKeypair` — pass
``algorithms=("RS256",)`` explicitly."""

DEFAULT_CLOCK_SKEW_SECONDS = 30


AuditCallback = Callable[[Mapping[str, Any]], Awaitable[None] | None]


class AuthGuard:
    """JWT bearer-token verifier."""

    def __init__(
        self,
        *,
        audience: str | None = None,
        audiences: tuple[str, ...] | None = None,
        jwks: JWKSCache,
        trust_map: IssuerTrustMap | None = None,
        revocation: RevocationStore | None = None,
        may_act: MayActPolicy | None = None,
        algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS,
        clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
        tenant_id_claim: str = DEFAULT_TENANT_ID_CLAIM,
        tenant_slug_claim: str = DEFAULT_TENANT_SLUG_CLAIM,
        roles_claim: str = DEFAULT_ROLES_CLAIM,
        scope_claim: str = DEFAULT_SCOPE_CLAIM,
        audit: AuditCallback | None = None,
    ) -> None:
        # Normalize singular ``audience`` and plural ``audiences`` into one
        # internal tuple. Callers provide either form; an empty plural is
        # rejected to prevent "accepts any audience" footguns.
        if audience is not None and audiences is not None:
            raise ValueError("provide either audience or audiences, not both")
        if audiences is not None:
            if not audiences:
                raise ValueError("audiences must be non-empty")
            for entry in audiences:
                if not entry:
                    raise ValueError("audience entries must be non-empty")
            self._audiences: tuple[str, ...] = tuple(audiences)
        else:
            if not audience:
                raise ValueError("audience must be non-empty")
            self._audiences = (audience,)
        if not algorithms:
            raise ValueError("algorithms must be non-empty")
        for alg in algorithms:
            if alg.lower() == "none":
                raise ValueError(f"algorithm {alg!r} is forbidden")
        if clock_skew_seconds < 0:
            raise ValueError("clock_skew_seconds must be non-negative")

        self._jwks = jwks
        self._trust_map = trust_map
        self._revocation = revocation
        self._may_act = may_act
        self._algorithms = tuple(algorithms)
        self._clock_skew = clock_skew_seconds
        self._tenant_id_claim = tenant_id_claim
        self._tenant_slug_claim = tenant_slug_claim
        self._roles_claim = roles_claim
        self._scope_claim = scope_claim
        self._audit = audit

    @property
    def audience(self) -> str:
        """Primary audience.

        Kept singular for backwards compatibility with logging / diagnostic
        callers (``"Auth initialized. audience=%s"``). When configured with
        plural ``audiences``, returns the first entry — typically the
        Keycloak audience during dual-issuer migration windows.
        """
        return self._audiences[0]

    @property
    def audiences(self) -> tuple[str, ...]:
        """All accepted audiences.

        A token is accepted when its ``aud`` claim matches any value in
        the tuple — used during the gatekeeper-mints-internal-JWT migration
        to accept both the legacy Keycloak audience (``gatekeeper``) and
        the new internal-token audience (``platform-services``) in the
        same verifier.
        """
        return self._audiences

    async def __call__(self, request: Any) -> IdentityContext:
        """FastAPI dependency entry point.

        ``request`` is duck-typed as anything with ``.headers`` (a Mapping)
        and ``.state`` (an attribute container). Avoiding a hard FastAPI
        import keeps this module testable without the framework installed.
        """
        token = self._extract_bearer(request)
        identity = await self.verify(token)
        # Stash on request.state for downstream require_scope deps.
        try:
            request.state.identity = identity
        except AttributeError:
            # Some test doubles don't expose .state — that's fine; the
            # caller can still consume the returned identity directly.
            pass
        return identity

    async def verify(self, token: str) -> IdentityContext:
        """Validate ``token`` and return the verified :class:`IdentityContext`.

        Use this directly when you have a token in hand and don't have a
        request object — e.g. event-bus consumers verifying a producer's
        S2S token recorded on the event envelope.
        """
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
            # Should not happen — we just checked registered_issuers().
            raise InvalidToken("issuer not registered") from exc

        try:
            claims = pyjwt.decode(
                token,
                key=jwk.key,
                algorithms=list(self._algorithms),
                # PyJWT accepts a list for ``audience`` and verifies the
                # token's ``aud`` matches at least one entry. This is the
                # multi-audience contract documented on the AuthGuard
                # ``audiences`` property.
                audience=list(self._audiences),
                leeway=self._clock_skew,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except ExpiredSignatureError as exc:
            raise TokenExpired("token expired") from exc
        except ImmatureSignatureError as exc:
            raise InvalidToken("token not yet valid (nbf in future)") from exc
        except InvalidAudienceError as exc:
            raise InvalidToken(
                f"audience mismatch (expected one of {list(self._audiences)!r})"
            ) from exc
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

        jti = claims["jti"]
        if self._revocation is not None and await self._revocation.is_revoked(jti):
            raise TokenRevoked(f"token jti {jti!r} is revoked")

        actor = self._enforce_act_chain(claims)

        # Optional tenant slug — read from the configured claim if
        # present. Absent / non-string → None (informational field;
        # we don't reject the token over a malformed slug).
        slug_raw = claims.get(self._tenant_slug_claim)
        tenant_slug = slug_raw if isinstance(slug_raw, str) else None

        identity = IdentityContext(
            tenant_id=tenant_id,
            subject=claims["sub"],
            roles=self._roles(claims),
            scopes=self._scopes(claims),
            actor=actor,
            tenant_slug=tenant_slug,
            raw_claims=claims,
        )

        await self._emit_audit(
            decision="allow",
            identity=identity,
            jti=jti,
            iss=iss,
        )
        return identity

    # ------------------------------------------------------------------ helpers

    def _extract_bearer(self, request: Any) -> str:
        header = request.headers.get("Authorization") or request.headers.get("authorization")
        if not header:
            raise InvalidToken("missing Authorization header")
        prefix, _, token = header.partition(" ")
        if prefix.lower() != "bearer" or not token:
            raise InvalidToken("Authorization header is not a Bearer token")
        return token.strip()

    def _unverified_header(self, token: str) -> dict[str, Any]:
        try:
            return pyjwt.get_unverified_header(token)
        except DecodeError as exc:
            raise InvalidToken("malformed token header") from exc
        except InvalidTokenError as exc:
            raise InvalidToken(f"unable to read token header: {exc}") from exc

    def _unverified_claims(self, token: str) -> dict[str, Any]:
        try:
            # PyJWT >= 2: passing options.verify_signature=False (deprecated path)
            # vs the modern algorithms=[...] arg with verify=False at decode.
            # We use ``decode`` with ``options={"verify_signature": False}`` so
            # PyJWT runs its parser but skips crypto. Consumers MUST follow up
            # with a real verify() call.
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

    def _extract_tenant_id(self, claims: Mapping[str, Any]) -> UUID:
        raw = claims.get(self._tenant_id_claim)
        if raw is None:
            raise InvalidToken(f"missing tenant claim: {self._tenant_id_claim!r}")
        if not isinstance(raw, str):
            raise InvalidToken(f"tenant claim {self._tenant_id_claim!r} must be a UUID string")
        try:
            return UUID(raw)
        except ValueError as exc:
            raise InvalidToken(
                f"tenant claim {self._tenant_id_claim!r} is not a valid UUID"
            ) from exc

    async def _enforce_trust(self, tenant_id: UUID, iss: str) -> None:
        assert self._trust_map is not None  # narrowed by caller
        record = await self._trust_map.get(tenant_id)
        if record is None:
            raise InvalidToken(f"unknown tenant {tenant_id}")
        if record.expected_issuer != iss:
            raise IssuerNotTrusted(
                f"tenant {tenant_id} expects issuer {record.expected_issuer!r}, "
                f"token presents {iss!r}"
            )
        if record.suspended:
            raise TenantSuspended(f"tenant {tenant_id} is suspended")

    def _enforce_act_chain(self, claims: Mapping[str, Any]) -> str | None:
        """Walk the ``act`` chain; return the immediate-actor identifier.

        RFC 8693's ``act`` is a JSON object with at minimum ``sub`` and
        possibly its own nested ``act``. We accept a top-level ``act`` and
        recursively check every level against the may_act policy.

        Returns the identifier of the *immediate* actor (the one who minted
        this token), or ``None`` for a first-party (non-impersonated) token.
        """
        act = claims.get("act")
        if act is None:
            return None
        if not isinstance(act, Mapping):
            raise InvalidToken("'act' claim must be an object")

        immediate_actor: str | None = None
        current: Mapping[str, Any] | None = act
        depth = 0
        max_depth = 10
        while current is not None:
            if depth >= max_depth:
                # Defensive: pathological act chains never happen in practice.
                raise InvalidToken(f"act chain too deep (>{max_depth} hops)")
            actor_id = self._actor_identifier(current)
            if actor_id is None:
                raise InvalidToken("'act' entry missing actor identifier")
            if immediate_actor is None:
                immediate_actor = actor_id
            if self._may_act is not None and not self._may_act.is_authorized(
                actor_id, self._audiences[0]
            ):
                raise ActorNotAuthorized(
                    f"actor {actor_id!r} not authorized to act for {self._audiences[0]!r}"
                )
            nested = current.get("act")
            current = nested if isinstance(nested, Mapping) else None
            depth += 1
        return immediate_actor

    @staticmethod
    def _actor_identifier(entry: Mapping[str, Any]) -> str | None:
        # Prefer client_id (machine identity) over sub (which could be a
        # human user impersonated by the actor — wrong identity to gate on).
        for key in ("client_id", "azp", "sub"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _roles(self, claims: Mapping[str, Any]) -> frozenset[str]:
        raw = claims.get(self._roles_claim)
        if raw is None:
            return frozenset()
        if isinstance(raw, str):
            # Single string — accept comma- or space-separated.
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
            # OAuth 2.0: space-separated scope string.
            return frozenset(s for s in raw.split() if s)
        if isinstance(raw, list):
            return frozenset(str(s) for s in raw if isinstance(s, str))
        raise InvalidToken(f"scope claim {self._scope_claim!r} has unexpected shape")

    async def _emit_audit(
        self,
        *,
        decision: str,
        identity: IdentityContext | None = None,
        jti: str | None = None,
        iss: str | None = None,
        reason: str | None = None,
    ) -> None:
        if self._audit is None:
            return
        record: dict[str, Any] = {
            "decision": decision,
            "audience": self._audiences[0],
            "audiences": list(self._audiences),
            "ts_unix": time.time(),
        }
        if identity is not None:
            record["tenant_id"] = str(identity.tenant_id)
            record["tenant_slug"] = identity.tenant_slug
            record["subject"] = identity.subject
            record["actor"] = identity.actor
            record["scopes"] = sorted(identity.scopes)
        if jti is not None:
            record["jti"] = jti
        if iss is not None:
            record["iss"] = iss
        if reason is not None:
            record["reason"] = reason

        result = self._audit(record)
        if hasattr(result, "__await__"):
            await result  # type: ignore[func-returns-value]


def require_scope(*required: str) -> Callable[..., Awaitable[IdentityContext]]:
    """Build a FastAPI dependency that enforces ``required`` scopes.

    Expects an :class:`AuthGuard` to have run earlier in the dependency
    chain (or as middleware) and stashed the verified
    :class:`IdentityContext` on ``request.state.identity``. Raises
    :class:`ScopeRequired` if any required scope is unsatisfied; raises
    :class:`InvalidToken` if no identity has been bound to the request
    (mis-wired endpoint — fail closed).

    Required scopes accept :class:`Scope` enum members or raw strings
    interchangeably.
    """
    needed = frozenset(str(r) for r in required)

    async def dep(request: Any) -> IdentityContext:
        identity: IdentityContext | None = getattr(request.state, "identity", None)
        if identity is None:
            # AuthGuard didn't run — caller forgot to wire it.
            raise InvalidToken("no verified identity bound to request")
        if not needed:
            return identity
        missing = frozenset(s for s in needed if not identity.has_scope(s))
        if missing:
            raise ScopeRequired(missing_scopes=missing)
        return identity

    return dep


__all__ = [
    "DEFAULT_ALGORITHMS",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "DEFAULT_ROLES_CLAIM",
    "DEFAULT_SCOPE_CLAIM",
    "DEFAULT_TENANT_ID_CLAIM",
    "DEFAULT_TENANT_SLUG_CLAIM",
    "REQUIRED_CLAIMS",
    "AuthGuard",
    "require_scope",
]
