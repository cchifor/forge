"""Tests for the circuit breaker."""

import time

from service.client.circuit_breaker import CircuitBreaker


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_success_resets_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        time.sleep(0.02)
        assert cb.state == "half_open"
        assert cb.allow_request() is True

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)

        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == "closed"

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)

        assert cb.allow_request() is True
        cb.record_failure()
        assert cb.state == "open"

    def test_retry_after(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=10.0)
        cb.record_failure()
        assert cb.retry_after > 0
        assert cb.retry_after <= 10.0
