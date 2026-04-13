"""Unit tests for HTTP middleware stack."""

from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, Response
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(
    path: str = "/api/items",
    method: str = "GET",
    client_host: str = "127.0.0.1",
    client_port: int = 9999,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a minimal mock Request."""
    req = MagicMock(spec=Request)
    url = MagicMock()
    url.path = path
    req.url = url
    req.method = method
    req.query_params = {}
    req.headers = headers or {}
    client = MagicMock()
    client.host = client_host
    client.port = client_port
    req.client = client
    req.state = MagicMock()
    # Default: no user attached
    req.state.user = None
    req.state.correlation_id = None
    return req


def _ok_response(status_code: int = 200) -> Response:
    return Response(content=b"ok", status_code=status_code)


# ===================================================================
# RateLimitMiddleware
# ===================================================================

class TestRateLimitMiddleware:
    """Tests for the token-bucket rate limiter."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.middleware.rate_limit import RateLimitMiddleware
        self.RateLimitMiddleware = RateLimitMiddleware

    def _make_mw(self, **kwargs):
        app = MagicMock()
        return self.RateLimitMiddleware(app, **kwargs)

    @pytest.mark.asyncio
    async def test_allows_request_under_limit(self):
        mw = self._make_mw(requests_per_minute=60)
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request()

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 200
        call_next.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_returns_429_when_exhausted(self):
        mw = self._make_mw(requests_per_minute=1, burst=1)
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request()

        # First request consumes the single token
        await mw.dispatch(req, call_next)
        # Second request should be rejected
        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    @pytest.mark.asyncio
    async def test_burst_capacity(self):
        mw = self._make_mw(requests_per_minute=60, burst=5)
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request()

        # Should allow up to 5 rapid requests (burst bucket)
        for _ in range(5):
            resp = await mw.dispatch(req, call_next)
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_per_tenant_keying(self):
        mw = self._make_mw(requests_per_minute=1, burst=1)
        call_next = AsyncMock(return_value=_ok_response())

        # Tenant A request
        req_a = _make_request()
        user_a = MagicMock()
        user_a.customer_id = "tenant-a"
        req_a.state.user = user_a

        # Tenant B request
        req_b = _make_request()
        user_b = MagicMock()
        user_b.customer_id = "tenant-b"
        req_b.state.user = user_b

        # Both should succeed -- separate buckets
        resp_a = await mw.dispatch(req_a, call_next)
        resp_b = await mw.dispatch(req_b, call_next)

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

    @pytest.mark.asyncio
    async def test_skip_paths_bypasses_limiting(self):
        mw = self._make_mw(
            requests_per_minute=1, burst=1,
            skip_paths=["/health"],
        )
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request(path="/health")

        # Even after exhaustion, skipped path passes through
        for _ in range(5):
            resp = await mw.dispatch(req, call_next)
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_anonymous_key_when_no_user_no_client(self):
        mw = self._make_mw(requests_per_minute=60)
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request()
        req.client = None
        req.state.user = None

        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        mw = self._make_mw(requests_per_minute=600, burst=1)
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request()

        # Exhaust the single token
        await mw.dispatch(req, call_next)
        # Immediately should be throttled
        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 429

        # Simulate time passing so tokens refill
        key = mw._resolve_key(req)
        mw._buckets[key].last_refill -= 1.0  # 1 second ago

        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 200


# ===================================================================
# AuditMiddleware
# ===================================================================

class TestAuditMiddleware:
    """Tests for audit trail logging."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.middleware.audit import AuditMiddleware
        self.AuditMiddleware = AuditMiddleware

    def _make_mw(self, **kwargs):
        app = MagicMock()
        return self.AuditMiddleware(app, **kwargs)

    @pytest.mark.asyncio
    async def test_excluded_path_skips_audit(self):
        mw = self._make_mw()
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request(path="/health")

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_excluded_method_skips_audit(self):
        mw = self._make_mw()
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request(method="OPTIONS")

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_audit_calls_next_for_tracked_path(self):
        mw = self._make_mw()
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request(path="/api/items", method="POST")

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 200
        call_next.assert_awaited_once()


# ===================================================================
# CorrelationIdMiddleware
# ===================================================================

class TestCorrelationIdMiddleware:
    """Tests for X-Request-ID propagation."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.middleware.correlation import CorrelationIdMiddleware
        self.CorrelationIdMiddleware = CorrelationIdMiddleware

    def _make_mw(self):
        app = MagicMock()
        return self.CorrelationIdMiddleware(app)

    @pytest.mark.asyncio
    async def test_extracts_existing_header(self):
        mw = self._make_mw()
        resp = _ok_response()
        call_next = AsyncMock(return_value=resp)
        req = _make_request(headers={"X-Request-ID": "abc-123"})

        result = await mw.dispatch(req, call_next)

        assert result.headers["X-Request-ID"] == "abc-123"
        assert req.state.correlation_id == "abc-123"

    @pytest.mark.asyncio
    async def test_generates_id_when_missing(self):
        mw = self._make_mw()
        resp = _ok_response()
        call_next = AsyncMock(return_value=resp)
        req = _make_request(headers={})

        result = await mw.dispatch(req, call_next)

        cid = result.headers["X-Request-ID"]
        assert cid  # non-empty
        assert len(cid) == 16  # uuid4().hex[:16]

    @pytest.mark.asyncio
    async def test_echoes_id_in_response(self):
        mw = self._make_mw()
        resp = _ok_response()
        call_next = AsyncMock(return_value=resp)
        req = _make_request(headers={"X-Request-ID": "echo-me"})

        result = await mw.dispatch(req, call_next)

        assert result.headers["X-Request-ID"] == "echo-me"


# ===================================================================
# RequestLoggingMiddleware
# ===================================================================

class TestRequestLoggingMiddleware:
    """Tests for structured request logging."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.middleware.logging import RequestLoggingMiddleware
        self.RequestLoggingMiddleware = RequestLoggingMiddleware

    def _make_mw(self, **kwargs):
        app = MagicMock()
        return self.RequestLoggingMiddleware(app, **kwargs)

    @pytest.mark.asyncio
    async def test_calls_next_for_normal_request(self):
        mw = self._make_mw()
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request()

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skip_paths_still_calls_next(self):
        mw = self._make_mw(skip_paths=["/health"])
        call_next = AsyncMock(return_value=_ok_response())
        req = _make_request(path="/health")

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reraises_exception_from_next(self):
        mw = self._make_mw()
        call_next = AsyncMock(side_effect=RuntimeError("boom"))
        req = _make_request()

        with pytest.raises(RuntimeError, match="boom"):
            await mw.dispatch(req, call_next)
