"""JWKSCache tests.

Uses ``httpx.MockTransport`` for the upstream JWKS server and
``cryptography`` to mint real RSA keys so :class:`jwt.PyJWK` construction
exercises a realistic code path.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import patch

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from platform_auth.exceptions import InvalidToken
from platform_auth.jwks import JWKSCache

ISSUER = "https://idp.example.com/realms/platform"
JWKS_URI = "https://idp.example.com/realms/platform/protocol/openid-connect/certs"


def _build_jwk(kid: str) -> dict[str, Any]:
    """Build a real RSA JWK with the given kid."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk_str = pyjwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())
    jwk: dict[str, Any] = json.loads(jwk_str)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return jwk


def _jwks_response(*kids: str) -> dict[str, Any]:
    return {"keys": [_build_jwk(kid) for kid in kids]}


class _CallCounter:
    """Tracks how many times the mock JWKS endpoint was hit."""

    def __init__(self):
        self.count = 0

    def increment(self) -> None:
        self.count += 1


@pytest.fixture
def call_counter() -> _CallCounter:
    return _CallCounter()


def _make_transport(
    *,
    jwks: dict[str, Any] | None = None,
    counter: _CallCounter | None = None,
    fail_with: type[Exception] | int | None = None,
) -> httpx.MockTransport:
    """Build an httpx MockTransport that returns ``jwks`` as JSON.

    If ``fail_with`` is an Exception class, raise it. If it's an int, return
    that HTTP status. Otherwise return 200 with the JWKS payload.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.increment()
        if isinstance(fail_with, type) and issubclass(fail_with, Exception):
            raise fail_with("simulated network failure")
        if isinstance(fail_with, int):
            return httpx.Response(fail_with)
        assert jwks is not None
        return httpx.Response(200, json=jwks)

    return httpx.MockTransport(handler)


class TestRegistration:
    async def test_register_then_lookup_succeeds(self, call_counter):
        transport = _make_transport(jwks=_jwks_response("kid-1"), counter=call_counter)
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            key = await cache.get_signing_key(ISSUER, "kid-1")
            assert isinstance(key, pyjwt.PyJWK)
        assert call_counter.count == 1

    async def test_unregistered_issuer_raises_key_error(self):
        cache = JWKSCache(
            http_client=httpx.AsyncClient(transport=_make_transport(jwks={"keys": []}))
        )
        try:
            with pytest.raises(KeyError, match="not registered"):
                await cache.get_signing_key("https://untrusted.example.com", "kid-1")
        finally:
            await cache.aclose()

    async def test_register_empty_issuer_raises(self):
        cache = JWKSCache()
        try:
            with pytest.raises(ValueError, match="issuer must be non-empty"):
                cache.register_issuer("", JWKS_URI)
        finally:
            await cache.aclose()

    async def test_register_empty_uri_raises(self):
        cache = JWKSCache()
        try:
            with pytest.raises(ValueError, match="jwks_uri must be non-empty"):
                cache.register_issuer(ISSUER, "")
        finally:
            await cache.aclose()

    async def test_register_same_uri_is_idempotent(self, call_counter):
        transport = _make_transport(jwks=_jwks_response("kid-1"), counter=call_counter)
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            await cache.get_signing_key(ISSUER, "kid-1")  # populates cache
            cache.register_issuer(ISSUER, JWKS_URI)  # idempotent — should not clear
            # Same kid, no second fetch
            await cache.get_signing_key(ISSUER, "kid-1")
        assert call_counter.count == 1

    async def test_register_different_uri_clears_cache(self, call_counter):
        transport = _make_transport(jwks=_jwks_response("kid-1"), counter=call_counter)
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            await cache.get_signing_key(ISSUER, "kid-1")  # populates cache
            cache.register_issuer(ISSUER, JWKS_URI + "/v2")  # changes URI
            await cache.get_signing_key(ISSUER, "kid-1")  # forces re-fetch
        assert call_counter.count == 2

    async def test_registered_issuers_returns_set(self):
        cache = JWKSCache()
        cache.register_issuer(ISSUER, JWKS_URI)
        cache.register_issuer("https://other.example.com", "https://other.example.com/jwks")
        try:
            issuers = cache.registered_issuers()
            assert ISSUER in issuers
            assert "https://other.example.com" in issuers
            assert isinstance(issuers, frozenset)
        finally:
            await cache.aclose()


class TestCaching:
    async def test_subsequent_calls_use_cache(self, call_counter):
        transport = _make_transport(jwks=_jwks_response("kid-1"), counter=call_counter)
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            for _ in range(5):
                await cache.get_signing_key(ISSUER, "kid-1")
        assert call_counter.count == 1

    async def test_concurrent_calls_only_fetch_once(self, call_counter):
        transport = _make_transport(jwks=_jwks_response("kid-1"), counter=call_counter)
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            results = await asyncio.gather(
                *(cache.get_signing_key(ISSUER, "kid-1") for _ in range(10))
            )
        assert call_counter.count == 1
        assert all(isinstance(k, pyjwt.PyJWK) for k in results)

    async def test_unknown_kid_triggers_refresh(self, call_counter):
        # First response only has kid-1; second has kid-1 and kid-2.
        responses = iter(
            [
                _jwks_response("kid-1"),
                _jwks_response("kid-1", "kid-2"),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            call_counter.increment()
            return httpx.Response(200, json=next(responses))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            await cache.get_signing_key(ISSUER, "kid-1")  # fetch 1
            # Asking for kid-2 forces a refresh because kid-2 is missing.
            await cache.get_signing_key(ISSUER, "kid-2")  # fetch 2
        assert call_counter.count == 2

    async def test_kid_truly_unknown_after_refresh_raises_invalid_token(self):
        transport = _make_transport(jwks=_jwks_response("kid-1"))
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            with pytest.raises(InvalidToken, match="unknown signing key kid"):
                await cache.get_signing_key(ISSUER, "kid-missing")


class TestStaleServe:
    async def test_serves_stale_within_window_on_upstream_failure(
        self,
        call_counter,
        caplog: pytest.LogCaptureFixture,
    ):
        # First call succeeds; second fetch (after lifespan) fails; cache is
        # within stale window so it should serve the cached key + log a warning.
        responses: list[Any] = [
            _jwks_response("kid-1"),
            httpx.ConnectError,  # second fetch raises
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            call_counter.increment()
            r = responses[call_counter.count - 1]
            if isinstance(r, type) and issubclass(r, Exception):
                raise r("upstream down")
            return httpx.Response(200, json=r)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            cache = JWKSCache(
                http_client=http,
                lifespan_seconds=1,
                stale_max_seconds=60,
            )
            cache.register_issuer(ISSUER, JWKS_URI)

            # First fetch populates cache.
            await cache.get_signing_key(ISSUER, "kid-1")

            # Force lifespan elapse with a monkeypatched monotonic.
            real_monotonic = time.monotonic
            t0 = real_monotonic()

            with (
                patch(
                    "platform_auth.jwks.time.monotonic",
                    side_effect=lambda: t0 + 30.0,
                ),
                caplog.at_level("WARNING"),
            ):
                # Lifespan elapsed (1s); within stale window (60s).
                # Upstream fails — we should serve stale.
                key = await cache.get_signing_key(ISSUER, "kid-1")

        assert isinstance(key, pyjwt.PyJWK)
        assert call_counter.count == 2  # tried to refresh, failed
        assert any("jwks_fetch_failed_serving_stale" in r.message for r in caplog.records)

    async def test_refuses_stale_after_window_on_upstream_failure(self, call_counter):
        # First call succeeds; second fails; staleness window has elapsed → InvalidToken.
        responses: list[Any] = [
            _jwks_response("kid-1"),
            httpx.ConnectError,
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            call_counter.increment()
            r = responses[call_counter.count - 1]
            if isinstance(r, type) and issubclass(r, Exception):
                raise r("upstream down")
            return httpx.Response(200, json=r)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            cache = JWKSCache(
                http_client=http,
                lifespan_seconds=1,
                stale_max_seconds=10,
            )
            cache.register_issuer(ISSUER, JWKS_URI)
            await cache.get_signing_key(ISSUER, "kid-1")

            real_monotonic = time.monotonic
            t0 = real_monotonic()

            with patch(
                "platform_auth.jwks.time.monotonic",
                side_effect=lambda: t0 + 30.0,  # past stale_max
            ):
                with pytest.raises(InvalidToken, match="JWKS unavailable"):
                    await cache.get_signing_key(ISSUER, "kid-1")


class TestMalformedResponses:
    async def test_jwks_missing_keys_array_raises(self):
        transport = _make_transport(jwks={"not_keys": []})
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            with pytest.raises(InvalidToken, match="JWKS unavailable"):
                await cache.get_signing_key(ISSUER, "kid-1")

    async def test_jwks_with_only_unusable_keys_raises(self):
        # JWK without a kid → skipped. If all keys are unusable, the fetch
        # raises and we surface InvalidToken (no stale to fall back to).
        transport = _make_transport(jwks={"keys": [{"kty": "RSA", "n": "x"}]})
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            with pytest.raises(InvalidToken):
                await cache.get_signing_key(ISSUER, "kid-1")

    async def test_jwks_http_500_raises(self):
        transport = _make_transport(fail_with=500)
        async with httpx.AsyncClient(transport=transport) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            with pytest.raises(InvalidToken):
                await cache.get_signing_key(ISSUER, "kid-1")


class TestConstructorValidation:
    async def test_lifespan_must_be_positive(self):
        with pytest.raises(ValueError, match="lifespan_seconds must be positive"):
            JWKSCache(lifespan_seconds=0)

    async def test_stale_max_must_be_at_least_lifespan(self):
        with pytest.raises(ValueError, match="stale_max_seconds must be"):
            JWKSCache(lifespan_seconds=600, stale_max_seconds=300)


class TestMultipleIssuers:
    async def test_independent_caches_per_issuer(self, call_counter):
        issuer_b = "https://idp.example.com/realms/enterprise"
        jwks_uri_b = "https://idp.example.com/realms/enterprise/protocol/openid-connect/certs"

        def handler(request: httpx.Request) -> httpx.Response:
            call_counter.increment()
            kid = "kid-a" if str(request.url) == JWKS_URI else "kid-b"
            return httpx.Response(200, json=_jwks_response(kid))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            cache.register_issuer(issuer_b, jwks_uri_b)

            key_a = await cache.get_signing_key(ISSUER, "kid-a")
            key_b = await cache.get_signing_key(issuer_b, "kid-b")
            assert isinstance(key_a, pyjwt.PyJWK)
            assert isinstance(key_b, pyjwt.PyJWK)
        assert call_counter.count == 2


class TestKeycloakShapedJWKS:
    """Regression coverage for the Keycloak default JWKS shape: a signing
    key (``RS256 / use=sig``) alongside an encryption key
    (``RSA-OAEP / use=enc``). Pre-fix the cache aborted the entire fetch
    on the encryption key's PyJWKError ("Unable to find an algorithm"),
    leaving the signing key inaccessible — every authenticated request
    failed with ``JWKS unavailable for issuer``. This is the production
    bug that surfaced as the SPA's silent-refresh loop after the
    platform-auth migration."""

    @staticmethod
    def _enc_key_kc_default() -> dict[str, Any]:
        """A real Keycloak-issued ``use=enc`` RSA-OAEP entry, modulo the kid.

        ``RSA-OAEP`` has no PyJWT signing-algorithm registration, so
        ``PyJWK(raw)`` raises ``PyJWKError`` — exactly the failure path
        the cache must now skip past."""
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk_str = pyjwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())
        jwk: dict[str, Any] = json.loads(jwk_str)
        jwk["kid"] = "enc-key-kid"
        jwk["alg"] = "RSA-OAEP"
        jwk["use"] = "enc"
        return jwk

    async def test_signing_key_is_returned_when_enc_key_is_present(self):
        sig_key = _build_jwk("sig-kid")
        enc_key = self._enc_key_kc_default()
        keys_response = {"keys": [sig_key, enc_key]}

        async with httpx.AsyncClient(
            transport=_make_transport(jwks=keys_response)
        ) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            key = await cache.get_signing_key(ISSUER, "sig-kid")
        assert isinstance(key, pyjwt.PyJWK)

    async def test_enc_key_alone_yields_no_usable_signing_key(self):
        """When the JWKS document contains *only* an ``use=enc`` key, the
        cache must treat it as having no usable signing key and surface a
        clear ``InvalidToken`` (rather than crashing on PyJWKError)."""
        keys_response = {"keys": [self._enc_key_kc_default()]}
        async with httpx.AsyncClient(
            transport=_make_transport(jwks=keys_response)
        ) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            with pytest.raises(InvalidToken, match="JWKS unavailable"):
                await cache.get_signing_key(ISSUER, "any-kid")

    async def test_enc_key_is_skipped_even_when_listed_before_sig_key(self):
        """Order independence: putting the ``use=enc`` key first must not
        block the cache from reaching the signing key behind it."""
        sig_key = _build_jwk("sig-kid")
        enc_key = self._enc_key_kc_default()
        keys_response = {"keys": [enc_key, sig_key]}
        async with httpx.AsyncClient(
            transport=_make_transport(jwks=keys_response)
        ) as http:
            cache = JWKSCache(http_client=http)
            cache.register_issuer(ISSUER, JWKS_URI)
            key = await cache.get_signing_key(ISSUER, "sig-kid")
        assert isinstance(key, pyjwt.PyJWK)
