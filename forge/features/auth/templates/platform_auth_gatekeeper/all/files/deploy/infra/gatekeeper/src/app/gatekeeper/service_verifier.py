# src/app/gatekeeper/service_verifier.py
"""Pluggable client-credential verification for the gatekeeper /auth/token endpoint.

The verifier answers one question: *does this request actually represent the
service client_id it claims to be?* It does NOT decide what the verified
client may do — that's the registry's job (see
:mod:`app.gatekeeper.service_registry`).

Three implementations:

* :class:`PreSharedSecretVerifier` — dev / docker-compose. Reads
  ``client_secret`` from the form-encoded body, verifies argon2id hash
  from the registry, constant-time compare under the hood (argon2-cffi).
* :class:`ProjectedSATokenVerifier` — k8s production. Reads
  ``Authorization: Bearer <projected-sa-token>``, verifies via the
  cluster OIDC issuer's JWKS, maps ``system:serviceaccount:<ns>:<name>``
  to a registry ``client_id`` via the ``k8s_subject`` field. No shared
  secrets — the kubelet rotates these tokens automatically.
* (future) :class:`MtlsVerifier` — alternative for non-k8s prod (bare
  metal, ECS Fargate). Same shape, validates the client cert against a
  CA bundle.

All implementations share the protocol so swapping at deploy time is
an env-var change. Verifier failures raise :class:`ClientAuthError` —
the endpoint translates to RFC 6749 ``401 invalid_client`` /
``403 unauthorized_client`` codes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import jwt as pyjwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Request

from app.gatekeeper.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VerifiedClient:
    """A successfully-authenticated service client."""

    client_id: str


class ClientAuthError(Exception):
    """Verifier could not authenticate the caller as the claimed client_id.

    ``error_code`` follows RFC 6749 §5.2 ``error`` enumeration so the
    endpoint can return it directly: ``invalid_client`` (bad / missing
    credentials), ``unauthorized_client`` (recognised client but not
    permitted to use this grant).
    """

    def __init__(self, message: str, *, error_code: str = "invalid_client") -> None:
        super().__init__(message)
        self.error_code = error_code


class ClientCredentialVerifier(Protocol):
    """Authenticator for a service-to-service token request.

    Implementations validate whatever credential material the caller
    presented and return :class:`VerifiedClient` on success. They must not
    consult the registry's authorization data — that's the endpoint's job.
    """

    async def verify(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        request: Request,
    ) -> VerifiedClient: ...


class PreSharedSecretVerifier:
    """argon2id-hashed pre-shared-secret verifier (dev backend).

    Loads the registry once at construction; verification reads
    ``client_secret`` from the inbound form, looks up the entry, and
    delegates to argon2-cffi's ``verify`` (which is constant-time and
    raises ``VerifyMismatchError`` on a wrong secret).

    Hashes are pre-computed offline (the seed YAML stores hashes, never
    plaintext). Operators rotate by replacing the hash and restarting
    gatekeeper; calling services pick up the new secret via redeploy.
    """

    __slots__ = ("_registry", "_hasher")

    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry
        self._hasher = PasswordHasher()

    async def verify(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        request: Request,  # noqa: ARG002 — preshared ignores the request
    ) -> VerifiedClient:
        if not client_secret:
            raise ClientAuthError("client_secret required")

        entry = self._registry.lookup(client_id)
        if entry is None or not entry.secret_hash:
            # Either the client_id is unknown or the registry entry has no
            # pre-shared secret configured (e.g. k8s-only entry running
            # under the wrong verifier). Same response shape so an attacker
            # can't probe registry membership.
            raise ClientAuthError("invalid client credentials")

        try:
            self._hasher.verify(entry.secret_hash, client_secret)
        except VerifyMismatchError:
            raise ClientAuthError("invalid client credentials") from None
        except Exception as exc:
            # Malformed hash, unsupported parameters — log + reject.
            logger.error(
                "preshared_verifier_hash_error client_id=%s err=%s",
                client_id,
                exc,
            )
            raise ClientAuthError("invalid client credentials") from exc

        return VerifiedClient(client_id=client_id)


# ── ProjectedSATokenVerifier (k8s production) ────────────────────────────


_DEFAULT_JWKS_TTL_SECONDS = 600.0


class ProjectedSATokenVerifier:
    """k8s-OIDC-issued ServiceAccount token verifier (production).

    The kubelet projects a short-lived JWT into each pod at
    ``/var/run/secrets/kubernetes.io/serviceaccount/token`` (rotated
    automatically; typical TTL ~1 hour). The calling service forwards
    this token as ``Authorization: Bearer <…>`` on its
    ``POST /auth/token`` request.

    Verification flow:

    1. Pull the bearer from ``Authorization``.
    2. Parse the JWT, extract ``kid``.
    3. Resolve the matching JWK from the cluster OIDC issuer's JWKS
       (cached for :data:`_DEFAULT_JWKS_TTL_SECONDS`).
    4. Verify signature, ``iss``, ``aud``, ``exp`` via PyJWT.
    5. Read ``sub`` (``system:serviceaccount:<ns>:<name>``) and look up
       the registry entry whose ``k8s_subject`` matches.
    6. Reject if no registry match, or if the matched ``client_id``
       differs from the form-supplied one (the caller can't claim
       a different identity than their projected token attests).

    No shared secrets, no rotation drama. Operators rotate the SA
    audience by changing the projected-volume manifest; the JWKS
    refresh picks up new signing keys within the cache window.
    """

    __slots__ = (
        "_registry",
        "_oidc_issuer",
        "_jwks_uri",
        "_audience",
        "_http",
        "_lock",
        "_jwks",
        "_jwks_fetched_at",
        "_jwks_ttl",
    )

    def __init__(
        self,
        registry: ServiceRegistry,
        *,
        oidc_issuer: str,
        jwks_uri: str,
        audience: str,
        http: httpx.AsyncClient | None = None,
        jwks_ttl_seconds: float = _DEFAULT_JWKS_TTL_SECONDS,
    ) -> None:
        if not oidc_issuer:
            raise ValueError("oidc_issuer required for k8s verifier")
        if not jwks_uri:
            raise ValueError("jwks_uri required for k8s verifier")
        if not audience:
            raise ValueError("audience required for k8s verifier")

        self._registry = registry
        self._oidc_issuer = oidc_issuer
        self._jwks_uri = jwks_uri
        self._audience = audience
        self._http = http or httpx.AsyncClient(timeout=10.0)
        self._lock = asyncio.Lock()
        self._jwks: dict[str, Any] = {"keys": []}
        self._jwks_fetched_at = 0.0
        self._jwks_ttl = jwks_ttl_seconds

    async def verify(
        self,
        *,
        client_id: str,
        client_secret: str | None,  # noqa: ARG002 — k8s ignores form-secret
        request: Request,
    ) -> VerifiedClient:
        token = _extract_bearer(request)
        if not token:
            raise ClientAuthError("Authorization: Bearer <projected-sa-token> required")

        # Parse header to find kid before signature verification.
        try:
            header = pyjwt.get_unverified_header(token)
        except pyjwt.InvalidTokenError as exc:
            raise ClientAuthError(f"projected token unparseable: {exc}") from exc
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise ClientAuthError("projected token missing kid header")

        jwk = await self._get_jwk(kid)
        if jwk is None:
            raise ClientAuthError(f"projected token kid {kid!r} not in cluster JWKS")

        # k8s OIDC tokens are RS256 (RSA) by default; SA-issuer-discovery
        # docs note ES256 may also appear with newer KMS-backed issuers.
        # PyJWT's algorithm-from-jwk path handles both.
        algorithm = header.get("alg") or jwk.get("alg") or "RS256"
        public_key = pyjwt.PyJWK.from_dict(jwk).key

        try:
            claims = pyjwt.decode(
                token,
                key=public_key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._oidc_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise ClientAuthError("projected token expired") from exc
        except pyjwt.InvalidTokenError as exc:
            raise ClientAuthError(f"projected token invalid: {exc}") from exc

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub.startswith("system:serviceaccount:"):
            raise ClientAuthError(
                f"projected token sub {sub!r} is not a k8s service account"
            )

        # Map the SA subject to a registry entry. We DO NOT trust the
        # form-supplied ``client_id`` — only the registry-mapped one is
        # honoured. Mismatches with the form value are rejected so a
        # caller can't pose as a different identity than their token
        # attests to.
        entry = _registry_entry_for_subject(self._registry, sub)
        if entry is None:
            raise ClientAuthError(
                f"projected token sub {sub!r} not registered with any client_id",
                error_code="unauthorized_client",
            )
        if entry.client_id != client_id:
            raise ClientAuthError(
                f"client_id {client_id!r} does not match projected SA "
                f"subject {sub!r} (resolves to {entry.client_id!r})",
                error_code="unauthorized_client",
            )

        return VerifiedClient(client_id=entry.client_id)

    async def _get_jwk(self, kid: str) -> dict[str, Any] | None:
        """Return the JWK for ``kid`` from the cluster OIDC issuer's JWKS.

        Uses a single-flight refresh: at most one in-flight HTTP call
        when the cache expires. A miss after a refresh returns ``None``
        — a brand-new signing key would normally be visible by the next
        TTL window.
        """
        now = time.monotonic()
        if now - self._jwks_fetched_at < self._jwks_ttl:
            return _find_jwk(self._jwks, kid)

        async with self._lock:
            now = time.monotonic()
            if now - self._jwks_fetched_at >= self._jwks_ttl:
                await self._refresh_jwks()
        return _find_jwk(self._jwks, kid)

    async def _refresh_jwks(self) -> None:
        """Replace the cached JWKS document. Logs + retains the prior on
        failure so transient OIDC issuer outages don't open a window
        where every request is rejected."""
        try:
            resp = await self._http.get(self._jwks_uri, timeout=10.0)
            resp.raise_for_status()
            doc = resp.json()
            if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
                raise RuntimeError("JWKS response missing 'keys' array")
        except Exception as exc:
            logger.warning(
                "k8s_jwks_refresh_failed url=%s err=%s — keeping previous keys",
                self._jwks_uri,
                exc,
            )
            return
        self._jwks = doc
        self._jwks_fetched_at = time.monotonic()
        logger.info(
            "k8s_jwks_refreshed url=%s keys=%d",
            self._jwks_uri,
            len(doc["keys"]),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


# ── MtlsVerifier (non-k8s prod) ──────────────────────────────────────────


class MtlsVerifier:
    """mTLS-cert verifier for non-k8s prod deployments.

    The TLS-terminating reverse proxy (Traefik / nginx / envoy) presents
    the calling pod's client cert to gatekeeper as request headers:

    * ``X-SSL-Client-Verify`` = ``SUCCESS`` when the proxy's CA bundle
      validated the cert, anything else when not.
    * ``X-SSL-Client-S-DN``   = the cert's Subject DN, formatted by the
      proxy (Traefik uses RFC 2253; nginx uses its own format —
      configure the proxy to use RFC 2253 / Traefik's
      ``passTLSClientCert.info.subject.commonName=true`` style).

    Verification flow:

    1. Confirm ``X-SSL-Client-Verify == SUCCESS`` (the proxy validated).
    2. Read ``X-SSL-Client-S-DN``.
    3. Match against the registry entry whose ``mtls_subject`` equals
       the DN string verbatim. (No partial / regex match — that's a
       footgun in security code.)
    4. Reject when the form-supplied ``client_id`` doesn't equal the
       matched entry — same anti-impersonation rule the k8s verifier
       enforces.

    The reverse proxy does the actual TLS validation; gatekeeper trusts
    its assertions. This requires the proxy NOT to forward client-set
    versions of these headers — typical config strips them on inbound
    traffic before adding the proxy's own.
    """

    __slots__ = ("_registry", "_verify_header", "_dn_header")

    def __init__(
        self,
        registry: ServiceRegistry,
        *,
        verify_header: str = "x-ssl-client-verify",
        dn_header: str = "x-ssl-client-s-dn",
    ) -> None:
        self._registry = registry
        self._verify_header = verify_header.lower()
        self._dn_header = dn_header.lower()

    async def verify(
        self,
        *,
        client_id: str,
        client_secret: str | None,  # noqa: ARG002 — mtls ignores form-secret
        request: Request,
    ) -> VerifiedClient:
        verify_status = request.headers.get(self._verify_header) or request.headers.get(
            self._verify_header.upper()
        )
        if not verify_status or verify_status.upper() != "SUCCESS":
            raise ClientAuthError(
                "client cert not validated by reverse proxy",
            )

        dn = request.headers.get(self._dn_header) or request.headers.get(
            self._dn_header.upper()
        )
        if not dn:
            raise ClientAuthError(
                f"reverse proxy did not forward {self._dn_header!r}",
            )

        entry = _registry_entry_for_mtls_subject(self._registry, dn)
        if entry is None:
            raise ClientAuthError(
                f"client cert subject {dn!r} not registered",
                error_code="unauthorized_client",
            )
        if entry.client_id != client_id:
            raise ClientAuthError(
                f"client_id {client_id!r} does not match cert subject {dn!r} "
                f"(resolves to {entry.client_id!r})",
                error_code="unauthorized_client",
            )
        return VerifiedClient(client_id=entry.client_id)


def _registry_entry_for_mtls_subject(registry: ServiceRegistry, dn: str) -> Any:
    for entry in registry.services:
        if entry.mtls_subject and entry.mtls_subject == dn:
            return entry
    return None


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    if not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip() or None


def _find_jwk(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            return jwk
    return None


def _registry_entry_for_subject(registry: ServiceRegistry, subject: str) -> Any:
    """Linear scan registry for the entry whose ``k8s_subject`` matches.

    Registry size is bounded by the number of internal services
    (handful in practice); a dict index is overkill.
    """
    for entry in registry.services:
        if entry.k8s_subject and entry.k8s_subject == subject:
            return entry
    return None


# ── Verifier construction ────────────────────────────────────────────────


def build_verifier(
    *,
    backend: str,
    registry: ServiceRegistry,
    k8s_oidc_issuer: str | None = None,
    k8s_jwks_uri: str | None = None,
    k8s_audience: str | None = None,
) -> ClientCredentialVerifier:
    """Construct the configured verifier from settings.

    Selection mirrors :class:`GatekeeperSettings.svc_auth_backend`:

    * ``preshared`` — :class:`PreSharedSecretVerifier`. No extra args.
    * ``k8s``       — :class:`ProjectedSATokenVerifier`. Requires
      ``k8s_oidc_issuer``, ``k8s_jwks_uri``, ``k8s_audience``.
    * ``mtls``      — :class:`MtlsVerifier`. No extra args; the proxy
      controls cert validation and subject extraction.
    """
    if backend == "preshared":
        return PreSharedSecretVerifier(registry)
    if backend == "k8s":
        if not (k8s_oidc_issuer and k8s_jwks_uri and k8s_audience):
            raise ValueError(
                "svc_auth_backend=k8s requires k8s_oidc_issuer, "
                "k8s_jwks_uri, and k8s_audience"
            )
        return ProjectedSATokenVerifier(
            registry,
            oidc_issuer=k8s_oidc_issuer,
            jwks_uri=k8s_jwks_uri,
            audience=k8s_audience,
        )
    if backend == "mtls":
        return MtlsVerifier(registry)
    raise ValueError(f"unknown svc_auth_backend: {backend!r}")


__all__ = [
    "ClientAuthError",
    "ClientCredentialVerifier",
    "MtlsVerifier",
    "PreSharedSecretVerifier",
    "ProjectedSATokenVerifier",
    "VerifiedClient",
    "build_verifier",
]
