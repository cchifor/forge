"""Task handler registry.

Register handlers with the ``@task_handler`` decorator::

    from service.tasks.registry import task_handler

    @task_handler("send_email")
    async def handle_send_email(payload: dict) -> dict | None:
        # do work...
        return {"sent": True}

Then enqueue tasks via the TaskService::

    await task_service.enqueue("send_email", payload={"to": "user@example.com"})
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# task_type -> handler coroutine
TaskHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]

_HANDLERS: dict[str, TaskHandler] = {}


def task_handler(task_type: str):
    """Decorator to register an async function as handler for a task type."""

    def decorator(fn: TaskHandler) -> TaskHandler:
        if task_type in _HANDLERS:
            logger.warning("Overwriting handler for task_type=%s", task_type)
        _HANDLERS[task_type] = fn
        logger.debug("Registered task handler: %s -> %s", task_type, fn.__qualname__)
        return fn

    return decorator


def get_handler(task_type: str) -> TaskHandler | None:
    return _HANDLERS.get(task_type)


def registered_types() -> list[str]:
    return list(_HANDLERS.keys())
