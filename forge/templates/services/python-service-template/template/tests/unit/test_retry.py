"""Tests for the retry policy."""

import pytest

from service.client.retry import RetryPolicy


class TestRetryPolicy:
    async def test_no_retry_on_success(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        result = await policy.execute(fn)
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_failure(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "recovered"

        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        result = await policy.execute(fn)
        assert result == "recovered"
        assert call_count == 3

    async def test_exhausts_retries(self):
        async def fn():
            raise ConnectionError("always fails")

        policy = RetryPolicy(max_retries=2, base_delay=0.01)
        with pytest.raises(ConnectionError):
            await policy.execute(fn)

    async def test_non_retryable_exception(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            retryable=lambda exc: isinstance(exc, ConnectionError),
        )
        with pytest.raises(ValueError):
            await policy.execute(fn)
        assert call_count == 1

    async def test_zero_retries(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        policy = RetryPolicy(max_retries=0, base_delay=0.01)
        with pytest.raises(ConnectionError):
            await policy.execute(fn)
        assert call_count == 1
