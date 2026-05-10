"""S2SClient tenant_id extension — covers per-tenant cache and form-data behaviour.

The platform's gatekeeper /auth/token accepts a ``tenant_id`` form
parameter alongside the standard OAuth2 ``client_credentials`` body.
Each calling service has one ``client_id`` per service identity (e.g.
``svc-workflow``) but acts on many tenants — caching tokens globally
would leak one tenant's authority into another's call. The extension:

* Sends ``tenant_id`` in the form data only on ``client_credentials``;
  token-exchange takes its tenant from ``subject_token`` so the param
  is suppressed there.
* Includes ``tenant_id`` in the cache key so tokens for different
  tenants don't share an entry.
* Backwards-compatible: omitting ``tenant_id`` reproduces today's
  behaviour exactly.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt as pyjwt
import pytest

from platform_auth.s2s_client import S2SClient

TOKEN_ENDPOINT = "http://gatekeeper:5000/auth/token"
AUDIENCE = "svc-knowledge"


class _RecordingIdp:
    """Returns a unique token per (form-body) request and records the form."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._counter = 0

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            body = parse_qs(request.content.decode(), keep_blank_values=False)
            flat = {k: v[0] if len(v) == 1 else v for k, v in body.items()}
            self.calls.append(flat)
            self._counter += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{self._counter}",
                    "expires_in": 300,
                    "token_type": "Bearer",
                },
            )

        return httpx.MockTransport(handler)


@pytest.fixture
def idp() -> _RecordingIdp:
    return _RecordingIdp()


@pytest.fixture
async def client(idp: _RecordingIdp):
    async with httpx.AsyncClient(transport=idp.transport()) as http:
        yield S2SClient(
            audience=AUDIENCE,
            token_endpoint=TOKEN_ENDPOINT,
            client_id="svc-workflow",
            client_secret="secret",
            http=http,
        )


# ── client_credentials with tenant_id ─────────────────────────────────────


class TestClientCredentialsWithTenant:
    async def test_sends_tenant_id_in_form_body(
        self,
        client: S2SClient,
        idp: _RecordingIdp,
    ) -> None:
        await client.get_token(tenant_id="00000000-0000-0000-0000-000000000001")
        assert idp.calls[0]["grant_type"] == "client_credentials"
        assert idp.calls[0]["tenant_id"] == "00000000-0000-0000-0000-000000000001"

    async def test_omits_tenant_id_when_not_provided(
        self,
        client: S2SClient,
        idp: _RecordingIdp,
    ) -> None:
        await client.get_token()
        assert "tenant_id" not in idp.calls[0]

    async def test_caches_per_tenant(
        self,
        client: S2SClient,
        idp: _RecordingIdp,
    ) -> None:
        # Two distinct tenants → two separate calls to the token endpoint.
        token_a = await client.get_token(tenant_id="tenant-a")
        token_b = await client.get_token(tenant_id="tenant-b")
        token_a_again = await client.get_token(tenant_id="tenant-a")  # cache hit

        assert token_a != token_b
        assert token_a == token_a_again
        assert len(idp.calls) == 2

    async def test_tenant_call_does_not_share_cache_with_no_tenant(
        self,
        client: S2SClient,
        idp: _RecordingIdp,
    ) -> None:
        # A call with no tenant_id is a different cache entry from a call
        # with a tenant — even if the server happens to ignore the field.
        await client.get_token()
        await client.get_token(tenant_id="tenant-a")
        assert len(idp.calls) == 2

    async def test_invalidate_targets_specific_tenant(
        self,
        client: S2SClient,
        idp: _RecordingIdp,
    ) -> None:
        await client.get_token(tenant_id="tenant-a")
        await client.get_token(tenant_id="tenant-b")
        assert len(idp.calls) == 2

        client.invalidate(tenant_id="tenant-a")

        # A re-fetch for tenant-a goes to the IdP; tenant-b stays cached.
        await client.get_token(tenant_id="tenant-a")
        await client.get_token(tenant_id="tenant-b")
        assert len(idp.calls) == 3


# ── token-exchange ignores tenant_id ──────────────────────────────────────


def _user_jwt(jti: str = "u-1", tenant: str = "user-tenant") -> str:
    """Minimal parseable JWT — used to exercise the obo cache-key path."""
    return pyjwt.encode(
        {
            "iss": "http://gatekeeper:5000",
            "sub": "user-1",
            "aud": "platform-services",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "jti": jti,
            "https://platform/tenant_id": tenant,
        },
        "some-test-secret-padded-out-to-32-chars-min!",
        algorithm="HS256",
    )


class TestCacheStats:
    async def test_first_call_is_a_miss(
        self,
        client: S2SClient,
        idp: _RecordingIdp,  # noqa: ARG002
    ) -> None:
        await client.get_token()
        stats = client.cache_stats()
        assert stats.misses == 1
        assert stats.hits == 0
        assert stats.hit_rate == 0.0

    async def test_second_identical_call_is_a_hit(
        self,
        client: S2SClient,
        idp: _RecordingIdp,  # noqa: ARG002
    ) -> None:
        await client.get_token()
        await client.get_token()
        stats = client.cache_stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.hit_rate == 0.5

    async def test_distinct_tenants_are_distinct_misses(
        self,
        client: S2SClient,
        idp: _RecordingIdp,  # noqa: ARG002
    ) -> None:
        await client.get_token(tenant_id="t-1")
        await client.get_token(tenant_id="t-2")
        await client.get_token(tenant_id="t-1")  # cache hit on t-1
        stats = client.cache_stats()
        assert stats.misses == 2
        assert stats.hits == 1


class TestTokenExchangeIgnoresTenant:
    async def test_does_not_send_tenant_id_on_token_exchange(
        self,
        client: S2SClient,
        idp: _RecordingIdp,
    ) -> None:
        await client.get_token(
            on_behalf_of=_user_jwt(),
            tenant_id="ignored-tenant",  # token-exchange takes tenant from subject_token
        )
        assert idp.calls[0]["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
        assert "tenant_id" not in idp.calls[0]

    async def test_obo_cache_still_keyed_by_tenant_when_set(
        self,
        client: S2SClient,
        idp: _RecordingIdp,
    ) -> None:
        """The obo cache differentiates entries by tenant even though the
        endpoint itself ignores the parameter — defends against a future
        endpoint that does honour tenant on token-exchange."""
        user = _user_jwt(jti="u-shared")
        await client.get_token(on_behalf_of=user, tenant_id="t-1")
        await client.get_token(on_behalf_of=user, tenant_id="t-2")
        assert len(idp.calls) == 2
