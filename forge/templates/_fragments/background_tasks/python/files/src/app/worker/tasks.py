"""Example task. Replace / extend with project-specific work.

Tasks are plain async functions decorated with ``@broker.task``. Kick one
off from a request handler or another task with ``await hello_task.kiq(...)``
which returns an ``AsyncTaskiqTask`` handle; await its ``.wait_result()``
if you need the return value.
"""

from __future__ import annotations

import logging

from app.worker.broker import broker

logger = logging.getLogger(__name__)


@broker.task
async def hello_task(name: str) -> str:
    """Toy task that logs a greeting and returns it."""
    message = f"hello, {name}"
    logger.info("hello_task executed: %s", message)
    return message
