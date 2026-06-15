"""S2SClient tests covering token-exchange, caching, and retry behavior."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import httpx
import jwt as pyjwt
import pytest

from platform_auth.exceptions import S2SAuthError
from platform_auth.s2s_client import S2SClient

TOKEN_ENDPOINT = "https://idp.example.com/realms/platform/protocol/openid-connect/token"
DOWNSTREAM_URL = "https://knowledge.svc/api/items"
AUDIENCE = "svc-knowledge"


class _MockIdp:
    """Stand-in for Keycloak's token endpoint plus a downstream service.

    All requests routed through ``httpx.MockTransport`` matching on URL.
    Tracks every request so tests can assert on what was sent.
    """

    def __init__(
        self,
        *,
        access_token: str = "access-token-1",
        expires_in: int = 300,
        downstream_status: int = 200,
        downstream_body: dict[str, Any] | None = None,
        token_endpoint_status: int = 200,
    ):
        self.access_token = access_token
        self.expires_in = expires_in
        self.downstream_status = downstream_status
        self.downstream_body = downstream_body or {"ok": True}
        self.token_endpoint_status = token_endpoint_status
        self.token_endpoint_calls: list[dict[str, Any]] = []
        self.downstream_calls: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == TOKEN_ENDPOINT:
                self.token_endpoint_calls.append(_form_to_dict(request))
                if self.token_endpoint_status != 200:
                    return httpx.Response(self.token_endpoint_status, text="upstream error")
                return httpx.Response(
                    200,
                    json={
                        "access_token": self.access_token,
                        "expires_in": self.expires_in,
                        "token_type": "Bearer",
                    },
                )
            # Downstream service.
            self.downstream_calls.append(request)
            return httpx.Response(self.downstream_status, json=self.downstream_body)

        return httpx.MockTransport(handler)


def _form_to_dict(request: httpx.Request) -> dict[str, Any]:
    """Decode an application/x-www-form-urlencoded request body."""
    from urllib.parse import parse_qs

    body = request.content.decode()
    parsed = parse_qs(body, keep_blank_values=False)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


_TEST_HMAC_SECRET = "test-secret-padded-to-32-chars-min!"


def _user_token(jti: str = "user-jti-1") -> str:
    """Build a minimal user token (signature not verified — we just need a
    parseable JWT for cache-key extraction)."""
    return pyjwt.encode(
        {
            "iss": "https://idp.example.com/realms/platform",
            "sub": "user-1",
            "aud": "svc-frontdoor",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "jti": jti,
        },
        _TEST_HMAC_SECRET,
        algorithm="HS256",
    )


# --------------------------------------------------------------- happy paths


class TestClientCredentials:
    async def test_first_call_obtains_token(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret-1",
                http=http,
            )
            token = await client.get_token()
            assert token == "access-token-1"

        assert len(idp.token_endpoint_calls) == 1
        body = idp.token_endpoint_calls[0]
        assert body["grant_type"] == "client_credentials"
        assert body["client_id"] == "svc-workflow"
        assert body["client_secret"] == "secret-1"
        assert body["audience"] == AUDIENCE

    async def test_subsequent_calls_use_cache(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            for _ in range(5):
                await client.get_token()
        assert len(idp.token_endpoint_calls) == 1

    async def test_cache_expires(self):
        idp = _MockIdp(expires_in=120)
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
                safety_margin_seconds=60,
            )
            t0 = time.monotonic()
            await client.get_token()  # cached for 60s (120-60 safety margin)

            with patch("platform_auth.s2s_client.time.monotonic", return_value=t0 + 200):
                await client.get_token()  # should refetch

        assert len(idp.token_endpoint_calls) == 2


class TestTokenExchange:
    async def test_obo_uses_token_exchange_grant(self):
        idp = _MockIdp(access_token="exchanged-token-1")
        user_token = _user_token()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            token = await client.get_token(on_behalf_of=user_token)
            assert token == "exchanged-token-1"

        body = idp.token_endpoint_calls[0]
        assert body["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
        assert body["subject_token"] == user_token
        assert body["subject_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
        assert body["audience"] == AUDIENCE

    async def test_obo_caches_per_user_jti(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            user_a = _user_token(jti="user-a-jti")
            user_b = _user_token(jti="user-b-jti")
            await client.get_token(on_behalf_of=user_a)
            await client.get_token(on_behalf_of=user_a)  # cache hit
            await client.get_token(on_behalf_of=user_b)
        assert len(idp.token_endpoint_calls) == 2  # a + b, no duplicate for a

    async def test_obo_falls_back_to_hash_when_jti_unparseable(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            # Garbage subject_token — not a JWT. Cache key should still be deterministic.
            await client.get_token(on_behalf_of="not-a-jwt")
            await client.get_token(on_behalf_of="not-a-jwt")
        assert len(idp.token_endpoint_calls) == 1

    async def test_client_credentials_and_obo_have_separate_cache(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            await client.get_token()
            await client.get_token(on_behalf_of=_user_token())
        assert len(idp.token_endpoint_calls) == 2


# ---------------------------------------------------------- HTTP convenience


class TestHttpConvenience:
    async def test_get_attaches_bearer(self):
        idp = _MockIdp(access_token="t-1")
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            response = await client.get(DOWNSTREAM_URL)
        assert response.status_code == 200
        downstream_request = idp.downstream_calls[0]
        assert downstream_request.headers["authorization"] == "Bearer t-1"

    async def test_post_put_patch_delete(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            for method in ("post", "put", "patch", "delete"):
                response = await getattr(client, method)(DOWNSTREAM_URL, json={"ok": 1})
                assert response.status_code == 200

    async def test_extra_headers_preserved(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            await client.get(DOWNSTREAM_URL, headers={"X-Trace-Id": "abc"})
        assert idp.downstream_calls[0].headers["x-trace-id"] == "abc"


# ------------------------------------------------------- 401 retry behavior


class TestRetryOn401:
    async def test_401_invalidates_cache_and_retries_once(self):
        # Toggle: first downstream call returns 401, second returns 200.
        downstream_responses = iter([401, 200])

        token_calls: list[dict[str, Any]] = []
        downstream_calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == TOKEN_ENDPOINT:
                token_calls.append(_form_to_dict(request))
                # Return a different token each time so we can verify the
                # second downstream attempt used the *new* token.
                idx = len(token_calls)
                return httpx.Response(
                    200,
                    json={"access_token": f"token-{idx}", "expires_in": 300},
                )
            downstream_calls.append(request)
            return httpx.Response(next(downstream_responses), json={"ok": True})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            response = await client.get(DOWNSTREAM_URL)

        assert response.status_code == 200
        # Token was refetched once after the 401.
        assert len(token_calls) == 2
        assert len(downstream_calls) == 2
        assert downstream_calls[0].headers["authorization"] == "Bearer token-1"
        assert downstream_calls[1].headers["authorization"] == "Bearer token-2"

    async def test_persistent_401_does_not_loop_forever(self):
        # Both attempts return 401; the client should give up and surface it.
        downstream_calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == TOKEN_ENDPOINT:
                return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
            downstream_calls.append(request)
            return httpx.Response(401, json={"error": "invalid_token"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            response = await client.get(DOWNSTREAM_URL)

        assert response.status_code == 401
        assert len(downstream_calls) == 2  # original + 1 retry, then surface


# ------------------------------------------------------------ failure modes


class TestFailureModes:
    async def test_token_endpoint_5xx_raises_s2s_error(self):
        idp = _MockIdp(token_endpoint_status=503)
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            with pytest.raises(S2SAuthError, match="HTTP 503"):
                await client.get_token()

    async def test_token_endpoint_unreachable_raises_s2s_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            with pytest.raises(S2SAuthError, match="unreachable"):
                await client.get_token()

    async def test_token_endpoint_returns_non_json(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>not json</html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            with pytest.raises(S2SAuthError, match="non-JSON"):
                await client.get_token()

    async def test_token_endpoint_response_missing_access_token(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"expires_in": 300})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            with pytest.raises(S2SAuthError, match="missing 'access_token'"):
                await client.get_token()

    async def test_token_endpoint_missing_expires_in_uses_default(
        self, caplog: pytest.LogCaptureFixture
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "t-1"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            with caplog.at_level("WARNING"):
                token = await client.get_token()
        assert token == "t-1"
        assert any("token_endpoint_missing_expires_in" in r.message for r in caplog.records)


# ---------------------------------------------------------- cache management


class TestCacheManagement:
    async def test_invalidate(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            await client.get_token()
            client.invalidate()
            await client.get_token()
        assert len(idp.token_endpoint_calls) == 2

    async def test_clear_cache(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            await client.get_token()
            await client.get_token(on_behalf_of=_user_token())
            client.clear_cache()
            await client.get_token()
            await client.get_token(on_behalf_of=_user_token())
        assert len(idp.token_endpoint_calls) == 4

    async def test_evict_when_cache_full(self):
        idp = _MockIdp()
        async with httpx.AsyncClient(transport=idp.transport()) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
                max_cache_entries=2,
            )
            # Fill: two distinct on_behalf_of users + 1 client_credentials = 3 entries.
            await client.get_token(on_behalf_of=_user_token(jti="u1"))
            await client.get_token(on_behalf_of=_user_token(jti="u2"))
            await client.get_token()  # this triggers eviction (size now 3 > max 2)
        assert len(idp.token_endpoint_calls) == 3


# ---------------------------------------------------- constructor validation


class TestConstructorValidation:
    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"audience": ""}, "audience must be non-empty"),
            ({"token_endpoint": ""}, "token_endpoint must be non-empty"),
            ({"client_id": ""}, "client_id must be non-empty"),
            ({"client_secret": ""}, "client_secret must be non-empty"),
            ({"max_cache_entries": 0}, "max_cache_entries must be positive"),
            ({"safety_margin_seconds": -1}, "safety_margin_seconds must be"),
        ],
    )
    async def test_invalid_args_rejected(self, kwargs, match):
        defaults = dict(
            audience=AUDIENCE,
            token_endpoint=TOKEN_ENDPOINT,
            client_id="svc-workflow",
            client_secret="secret",
        )
        defaults.update(kwargs)
        with pytest.raises(ValueError, match=match):
            S2SClient(**defaults)


# ------------------------------------------------------------- safe_text used


class TestLogSafety:
    async def test_long_failure_body_is_truncated(self):
        big_body = "x" * 5000
        idp_calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            idp_calls.append(request)
            return httpx.Response(500, text=big_body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = S2SClient(
                audience=AUDIENCE,
                token_endpoint=TOKEN_ENDPOINT,
                client_id="svc-workflow",
                client_secret="secret",
                http=http,
            )
            with pytest.raises(S2SAuthError) as exc_info:
                await client.get_token()
        # Ensure the 5000-char body did not end up verbatim in the exception's
        # stored ``extra``: log-safety helper truncates to 200.
        assert len(exc_info.value.extra["body"]) == 200
