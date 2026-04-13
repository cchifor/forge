"""Simple in-memory circuit breaker.

States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
- CLOSED: requests flow normally; failures are counted.
- OPEN: requests are rejected immediately for ``reset_timeout`` seconds.
- HALF_OPEN: a single probe request is allowed; success closes, failure re-opens.
"""

from __future__ import annotations

import time
from enum import StrEnum, auto


class _State(StrEnum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        half_open_max: int = 1,
    ):
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._half_open_max = half_open_max

        self._state = _State.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        self._maybe_transition()
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == _State.OPEN

    @property
    def retry_after(self) -> float:
        if self._state != _State.OPEN:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_time
        return max(0.0, self._reset_timeout - elapsed)

    def allow_request(self) -> bool:
        self._maybe_transition()
        if self._state == _State.CLOSED:
            return True
        if self._state == _State.HALF_OPEN:
            if self._half_open_calls < self._half_open_max:
                self._half_open_calls += 1
                return True
            return False
        return False  # OPEN

    def record_success(self) -> None:
        self._failure_count = 0
        self._half_open_calls = 0
        self._state = _State.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = _State.OPEN

    def _maybe_transition(self) -> None:
        if self._state == _State.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._reset_timeout:
                self._state = _State.HALF_OPEN
                self._half_open_calls = 0
