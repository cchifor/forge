"""``weld.core.context`` — request-scoped identity propagation (matrix-CI stub).

Exposes the surface auth fragment middleware depends on:
* ``customer_id_context`` / ``user_id_context`` ContextVars (set/reset)
* ``set_context(customer_id=..., user_id=...)`` helper that sets both
* ``get_customer_id()`` / ``get_user_id()`` readers
* ``reset_context()`` to clear both
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

customer_id_context: ContextVar[Any] = ContextVar("customer_id_context", default=None)
user_id_context: ContextVar[Any] = ContextVar("user_id_context", default=None)


class RequestContext:
    """Stub holding per-request identity."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def set_context(*, customer_id: Any = None, user_id: Any = None) -> tuple[Any, Any]:
    """Set both context vars, returning the tokens (for paired reset)."""
    return customer_id_context.set(customer_id), user_id_context.set(user_id)


def reset_context(tokens: tuple[Any, Any] | None = None) -> None:
    if tokens is None:
        customer_id_context.set(None)
        user_id_context.set(None)
        return
    customer_token, user_token = tokens
    customer_id_context.reset(customer_token)
    user_id_context.reset(user_token)


def get_customer_id() -> Any:
    return customer_id_context.get()


def get_user_id() -> Any:
    return user_id_context.get()


def get_current() -> RequestContext | None:
    return None
