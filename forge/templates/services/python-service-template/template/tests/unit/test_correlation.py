"""Tests for correlation ID utilities."""

from service.observability.correlation import (
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
)


class TestCorrelationId:
    def test_generate_returns_hex_string(self):
        cid = generate_correlation_id()
        assert len(cid) == 16
        int(cid, 16)  # Should not raise

    def test_set_and_get(self):
        set_correlation_id("test-123")
        assert get_correlation_id() == "test-123"

    def test_default_empty(self):
        # Reset by setting empty
        set_correlation_id("")
        assert get_correlation_id() == ""
