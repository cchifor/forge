"""Tests for service.client.base.ServiceClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from service.client.base import ServiceClient
from service.client.circuit_breaker import CircuitBreaker
from service.client.errors import CircuitOpenError, ServiceCallError
from service.client.retry import RetryPolicy


class TestServiceClientLifecycle:
    async def test_start_creates_client(self):
        sc = ServiceClient(base_url="http://svc:5000", service_name="test")
        await sc.start()
        try:
            assert sc.client is not None
        finally:
            await sc.stop()

    def test_client_not_started_raises(self):
        sc = ServiceClient(base_url="http://svc:5000", service_name="test")
        with pytest.raises(RuntimeError, match="not started"):
            _ = sc.client

    async def test_stop_closes_client(self):
        sc = ServiceClient(base_url="http://svc:5000", service_name="test")
        await sc.start()
        await sc.stop()
        assert sc._client is None


class TestServiceClientRequests:
    @pytest.fixture
    def sc(self):
        return ServiceClient(
            base_url="http://svc:5000",
            service_name="test",
            retry=RetryPolicy(max_retries=0),
            circuit_breaker=CircuitBreaker(failure_threshold=10),
        )

    def _mock_response(self, status_code=200, json_data=None):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.text = ""
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=resp,
            )
        return resp

    async def test_get_success(self, sc):
        mock_client = AsyncMock()
        mock_client.request.return_value = self._mock_response(200, {"ok": True})
        sc._client = mock_client

        result = await sc.get("/api/test")
        assert result == {"ok": True}

    async def test_post_success(self, sc):
        mock_client = AsyncMock()
        mock_client.request.return_value = self._mock_response(201, {"id": 1})
        sc._client = mock_client

        result = await sc.post("/api/test", json={"name": "x"})
        assert result == {"id": 1}

    async def test_204_returns_none(self, sc):
        mock_client = AsyncMock()
        mock_client.request.return_value = self._mock_response(204)
        sc._client = mock_client

        result = await sc.delete("/api/test/1")
        assert result is None

    async def test_propagates_correlation_id(self, sc):
        from service.observability.correlation import set_correlation_id
        set_correlation_id("req-123")
        try:
            mock_client = AsyncMock()
            mock_client.request.return_value = self._mock_response(200, {})
            sc._client = mock_client

            await sc.get("/api/test")
            call_kwargs = mock_client.request.call_args
            headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
            assert headers.get("X-Request-ID") == "req-123"
        finally:
            set_correlation_id("")

    async def test_circuit_open_raises(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()  # opens the circuit

        sc = ServiceClient(
            base_url="http://svc:5000",
            service_name="test",
            circuit_breaker=cb,
        )
        sc._client = AsyncMock()

        with pytest.raises(CircuitOpenError):
            await sc.get("/api/test")

    async def test_http_error_records_failure(self, sc):
        mock_client = AsyncMock()
        mock_client.request.return_value = self._mock_response(500)
        sc._client = mock_client

        with pytest.raises(ServiceCallError) as exc_info:
            await sc.get("/api/test")
        assert exc_info.value.status_code == 500

    async def test_connection_error_raises_service_call_error(self, sc):
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("refused")
        sc._client = mock_client

        with pytest.raises(ServiceCallError):
            await sc.get("/api/test")
