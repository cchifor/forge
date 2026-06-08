"""Per-request identity ``ContextVar`` set for out-of-band propagation.

Middleware / the auth layer sets the current caller's identity here at the
start of a request; code that runs *without* the request object in hand
(a unit-of-work resolving tenant scope, a logging filter, a background task
spawned from a request) reads it back. Using ``ContextVar`` keeps the values
correctly isolated per asyncio task.

The set is the generic identity trio every service needs: the tenant
(``customer_id``), the acting ``user_id``, and an optional human-readable
``tenant_slug`` (which may legitimately be absent on public endpoints or
background work, so its getter returns ``None`` rather than raising).
"""

from __future__ import annotations

from contextvars import ContextVar, Token

customer_id_context: ContextVar[str | None] = ContextVar("customer_id_context", default=None)
user_id_context: ContextVar[str | None] = ContextVar("user_id_context", default=None)
tenant_slug_context: ContextVar[str | None] = ContextVar("tenant_slug_context", default=None)


def get_customer_id() -> str:
    """Return the current tenant id, raising if it has not been set."""
    customer_id = customer_id_context.get()
    if customer_id is None:
        raise ValueError("customer_id is not set in the current context.")
    return customer_id


def get_user_id() -> str:
    """Return the current acting user id, raising if it has not been set."""
    user_id = user_id_context.get()
    if user_id is None:
        raise ValueError("user_id is not set in the current context.")
    return user_id


def get_tenant_slug() -> str | None:
    """Return the current tenant slug, or ``None`` when none is bound.

    Unlike ``customer_id`` / ``user_id`` a tenant slug may legitimately be
    absent (public endpoints, background tasks), so this returns ``None``
    instead of raising and lets the caller decide how to handle it.
    """
    return tenant_slug_context.get()


def set_context(customer_id: str, user_id: str, tenant_slug: str | None = None) -> list[Token]:
    """Bind the caller identity for the current context, returning reset tokens."""
    return [
        customer_id_context.set(customer_id),
        user_id_context.set(user_id),
        tenant_slug_context.set(tenant_slug),
    ]


def reset_context(tokens: list[Token]) -> None:
    """Restore the identity context from the tokens :func:`set_context` returned."""
    customer_id_context.reset(tokens[0])
    user_id_context.reset(tokens[1])
    if len(tokens) > 2:
        tenant_slug_context.reset(tokens[2])
