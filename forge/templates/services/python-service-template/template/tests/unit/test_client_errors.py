"""Tests for service.client.errors."""

from service.client.errors import CircuitOpenError, ServiceCallError


class TestServiceCallError:
    def test_basic_construction(self):
        err = ServiceCallError("svc", "GET", "http://example.com/api")
        assert err.service == "svc"
        assert err.method == "GET"
        assert err.url == "http://example.com/api"
        assert "svc" in str(err)

    def test_with_status_code(self):
        err = ServiceCallError("svc", "POST", "/api", status_code=500)
        assert err.status_code == 500
        assert "-> 500" in str(err)

    def test_without_status_code(self):
        err = ServiceCallError("svc", "GET", "/api")
        assert err.status_code is None
        assert "->" not in str(err)

    def test_with_cause(self):
        cause = ValueError("boom")
        err = ServiceCallError("svc", "GET", "/api", cause=cause)
        assert err.__cause__ is cause

    def test_with_body(self):
        err = ServiceCallError("svc", "GET", "/api", body={"error": "bad"})
        assert err.body == {"error": "bad"}


class TestCircuitOpenError:
    def test_construction(self):
        err = CircuitOpenError("svc", retry_after_seconds=30.0)
        assert err.retry_after_seconds == 30.0
        assert err.service == "svc"
        assert err.method == "*"

    def test_str_representation(self):
        err = CircuitOpenError("svc", retry_after_seconds=10.0)
        assert "Circuit breaker open" in str(err)
        assert "svc" in str(err)
        assert "10s" in str(err)
