"""Taskiq broker + result backend configuration.

Default to Redis for both; the broker URL is read once at import time so a
project without a Redis dep can still import this module (the broker is
constructed but never started).
"""

from __future__ import annotations

import os

from taskiq_redis import RedisAsyncResultBackend, ListQueueBroker


def _broker_url() -> str:
    return os.environ.get("TASKIQ_BROKER_URL", "redis://redis:6379/2")


def _result_url() -> str:
    return os.environ.get("TASKIQ_RESULT_BACKEND_URL", _broker_url())


broker = ListQueueBroker(url=_broker_url()).with_result_backend(
    RedisAsyncResultBackend(redis_url=_result_url())
)
