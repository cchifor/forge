"""Tests for service-to-service tenant context propagation."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from service.client.base import ServiceClient
from service.core import context


class FakeServiceClient(ServiceClient):
    """Test-only client that captures requests."""

    def __init__(self):
        super().__init__(
            base_url="http://notification:5001",
            service_name="notification",
        )


@pytest.fixture
async def s2s_client():
    client = FakeServiceClient()
    await client.start()
    yield client
    await client.stop()


class TestS2STenantPropagation:
    """Verify ServiceClient propagates tenant context headers."""

    @pytest.mark.asyncio
    async def test_propagates_customer_id_header(self, s2s_client):
        """S2S calls should include x-customer-id from context."""
        context.set_context(customer_id="tenant-123", user_id="user-456")

        with patch.object(
            s2s_client.client, "request", new_callable=AsyncMock
        ) as mock_req:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {"ok": True}
            mock_req.return_value = mock_resp

            await s2s_client.get("/api/v1/notifications")

            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert headers.get("x-customer-id") == "tenant-123"
            assert headers.get("x-gatekeeper-user-id") == "user-456"

    @pytest.mark.asyncio
    async def test_skips_headers_for_public_context(self, s2s_client):
        """Public context should not propagate tenant headers."""
        context.set_context(customer_id="public", user_id="anonymous")

        with patch.object(
            s2s_client.client, "request", new_callable=AsyncMock
        ) as mock_req:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {"ok": True}
            mock_req.return_value = mock_resp

            await s2s_client.get("/api/v1/health")

            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert "x-customer-id" not in headers
            assert "x-gatekeeper-user-id" not in headers

    @pytest.mark.asyncio
    async def test_propagates_correlation_id(self, s2s_client):
        """S2S calls should include correlation ID."""
        from service.observability.correlation import set_correlation_id

        set_correlation_id("req-789")
        context.set_context(customer_id="tenant-1", user_id="user-1")

        with patch.object(
            s2s_client.client, "request", new_callable=AsyncMock
        ) as mock_req:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {}
            mock_req.return_value = mock_resp

            await s2s_client.get("/api/v1/check")

            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert headers.get("X-Request-ID") == "req-789"

    @pytest.mark.asyncio
    async def test_no_error_when_context_not_set(self, s2s_client):
        """S2S calls should work even when no context is set."""
        # Reset context
        context.customer_id_context.set(None)
        context.user_id_context.set(None)

        with patch.object(
            s2s_client.client, "request", new_callable=AsyncMock
        ) as mock_req:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {}
            mock_req.return_value = mock_resp

            # Should not raise
            await s2s_client.get("/api/v1/health")
