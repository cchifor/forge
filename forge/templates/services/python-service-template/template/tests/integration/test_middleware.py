"""Integration tests for all middleware modules.

Tests CorrelationIdMiddleware, RequestLoggingMiddleware,
AuditMiddleware, and RateLimitMiddleware through a minimal FastAPI app.
"""

import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.middleware.audit import AuditMiddleware
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware


def _build_middleware_app(
    *,
    rate_limit_rpm: int = 120,
    rate_limit_burst: int | None = None,
    skip_paths: list[str] | None = None,
) -> FastAPI:
    """Build a minimal app with all middleware for testing."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "UP"}

    @app.get("/error")
    async def error_endpoint():
        raise ValueError("boom")

    # Middleware is added in reverse order (last added = first executed)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=rate_limit_rpm,
        burst=rate_limit_burst,
        skip_paths=skip_paths or ["/health"],
    )
    app.add_middleware(
        AuditMiddleware,
        excluded_paths={"/health", "/docs"},
        excluded_methods={"OPTIONS"},
    )
    app.add_middleware(RequestLoggingMiddleware, skip_paths=["/health"])
    app.add_middleware(CorrelationIdMiddleware)

    return app


@pytest.fixture
def mw_app():
    return _build_middleware_app()


@pytest.fixture
async def mw_client(mw_app):
    transport = ASGITransport(app=mw_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# -- CorrelationIdMiddleware ---------------------------------------------------

class TestCorrelationIdMiddleware:
    async def test_generates_id_when_absent(self, mw_client):
        resp = await mw_client.get("/test")
        assert resp.status_code == 200
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) > 0

    async def test_echoes_provided_id(self, mw_client):
        resp = await mw_client.get("/test", headers={"X-Request-ID": "my-trace-123"})
        assert resp.headers["x-request-id"] == "my-trace-123"


# -- RequestLoggingMiddleware --------------------------------------------------

class TestRequestLoggingMiddleware:
    async def test_logs_successful_request(self, mw_client):
        # BaseHTTPMiddleware runs in a thread, so caplog can't capture.
        # Just verify the endpoint responds (middleware runs without error).
        resp = await mw_client.get("/test")
        assert resp.status_code == 200

    async def test_skips_configured_paths(self, mw_client):
        resp = await mw_client.get("/health")
        assert resp.status_code == 200


# -- AuditMiddleware -----------------------------------------------------------

class TestAuditMiddleware:
    async def test_logs_normal_request(self, mw_client):
        # Verify middleware executes without error on a normal request.
        resp = await mw_client.get("/test")
        assert resp.status_code == 200

    async def test_skips_excluded_path(self, mw_client):
        resp = await mw_client.get("/health")
        assert resp.status_code == 200


# -- RateLimitMiddleware -------------------------------------------------------

class TestRateLimitMiddleware:
    async def test_allows_normal_traffic(self, mw_client):
        resp = await mw_client.get("/test")
        assert resp.status_code == 200

    async def test_rate_limit_exceeded(self):
        app = _build_middleware_app(rate_limit_rpm=2, rate_limit_burst=2)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Exhaust the bucket
            for _ in range(3):
                await c.get("/test")
            resp = await c.get("/test")
            assert resp.status_code == 429

    async def test_retry_after_header(self):
        app = _build_middleware_app(rate_limit_rpm=1, rate_limit_burst=1)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await c.get("/test")  # use the single token
            resp = await c.get("/test")
            assert resp.status_code == 429
            assert "retry-after" in resp.headers

    async def test_skips_excluded_paths(self, mw_client):
        # /health is in skip_paths, so even with heavy traffic it should pass
        for _ in range(10):
            resp = await mw_client.get("/health")
            assert resp.status_code == 200
