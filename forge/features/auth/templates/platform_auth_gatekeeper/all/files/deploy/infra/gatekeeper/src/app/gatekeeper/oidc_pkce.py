# src/app/gatekeeper/oidc_pkce.py
"""
Pure, dependency-free OIDC PKCE + nonce + bound-state primitives (WS-2.5).

This module deliberately imports only the Python standard library so it can
be unit-tested in isolation (no fastapi / redis / PyJWT). It provides:

* :func:`generate_pkce_verifier` — an RFC 7636 ``code_verifier`` (43-128
  characters drawn from the unreserved set, no padding).
* :func:`pkce_challenge_s256` — the S256 ``code_challenge`` for a verifier,
  i.e. ``BASE64URL-ENCODE(SHA256(ASCII(code_verifier)))`` with padding
  stripped (RFC 7636 §4.2).
* :func:`generate_state` / :func:`generate_nonce` — high-entropy, URL-safe,
  single-use opaque values for CSRF-binding (``state``) and replay-binding
  (``nonce``) the Authorization Code flow.
* :func:`nonces_equal` — a constant-time, ``None``-safe equality check used
  to compare the nonce echoed back in the ``id_token`` against the value we
  stored server-side.
* :func:`envelope_code_verifier` / :func:`envelope_nonce` — fail-closed
  extractors that pull the ``code_verifier`` / ``nonce`` out of a popped
  bound-state envelope, raising :class:`ValueError` when the value is
  absent or empty (never returning an empty default that would silently
  disable PKCE / nonce binding).

Reference: RFC 7636 (PKCE) and OpenID Connect Core §3.1.2.1 (nonce).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from typing import Any

# 32 random bytes → ~43 url-safe chars; 64 → ~86 chars. Both sit inside the
# RFC 7636 [43, 128] verifier-length window, so the raw token_urlsafe output
# needs no slicing.
_VERIFIER_ENTROPY_BYTES = 64
_OPAQUE_ENTROPY_BYTES = 32


def generate_pkce_verifier() -> str:
    """Return a fresh RFC 7636 ``code_verifier``.

    ``secrets.token_urlsafe`` emits characters from ``[A-Za-z0-9-_]`` (a
    subset of the RFC 7636 unreserved set ``[A-Za-z0-9-._~]``) with no
    padding, so the result is a valid verifier as-is. With 64 bytes of
    entropy the string is ~86 characters — comfortably within [43, 128].
    """
    return secrets.token_urlsafe(_VERIFIER_ENTROPY_BYTES)


def pkce_challenge_s256(code_verifier: str) -> str:
    """Compute the S256 ``code_challenge`` for *code_verifier*.

    ``BASE64URL-ENCODE(SHA256(ASCII(code_verifier)))`` with trailing ``=``
    padding removed, per RFC 7636 §4.2.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """Return a high-entropy, URL-safe, single-use ``state`` value.

    Used as the server-side lookup key binding the browser session to the
    Authorization Code flow (CSRF defense). The originally-requested return
    URI is NOT placed in ``state`` — it lives in the server-side envelope —
    so this value can be opaque random.
    """
    return secrets.token_urlsafe(_OPAQUE_ENTROPY_BYTES)


def generate_nonce() -> str:
    """Return a high-entropy, URL-safe, single-use OIDC ``nonce`` value.

    Sent on the authorization request and echoed back inside the
    ``id_token``; comparing the two defeats token replay/injection.
    """
    return secrets.token_urlsafe(_OPAQUE_ENTROPY_BYTES)


def nonces_equal(expected: str | None, actual: str | None) -> bool:
    """Constant-time, ``None``-safe equality check for nonce comparison.

    Returns ``False`` whenever either side is ``None`` **or empty** so a
    missing/blank nonce fails closed (an empty ``expected`` must never match
    an empty ``actual``). Uses :func:`hmac.compare_digest` to avoid leaking
    match length via timing — cheap insurance even though the nonce is not a
    long-lived secret.
    """
    if not expected or not actual:
        return False
    return hmac.compare_digest(expected, actual)


def envelope_code_verifier(envelope: Mapping[str, Any]) -> str:
    """Return the non-empty PKCE ``code_verifier`` from *envelope*.

    Fail-closed: raises :class:`ValueError` when the key is missing, not a
    string, or empty. This prevents an empty verifier from being sent to the
    token endpoint (which would silently defeat PKCE).
    """
    value = envelope.get("code_verifier")
    if not isinstance(value, str) or not value:
        raise ValueError("bound-state envelope is missing a code_verifier")
    return value


def envelope_nonce(envelope: Mapping[str, Any]) -> str:
    """Return the non-empty OIDC ``nonce`` from *envelope*.

    Fail-closed: raises :class:`ValueError` when the key is missing, not a
    string, or empty. This prevents an empty expected-nonce that could
    spuriously match an empty ``id_token`` nonce.
    """
    value = envelope.get("nonce")
    if not isinstance(value, str) or not value:
        raise ValueError("bound-state envelope is missing a nonce")
    return value
