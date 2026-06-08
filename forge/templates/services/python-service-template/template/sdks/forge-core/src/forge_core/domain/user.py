"""The authenticated-principal model an auth layer hydrates from a token.

:class:`User` is the validated, request-scoped principal a security layer
builds after verifying a bearer token, and that a service injects into its
handlers. It carries the generic identity claims every service needs — a
stable id, a username / email, a display name, the caller's roles and its
tenant (``customer_id``) — plus the optional ``org_id`` sub-grouping, a
``service_account`` flag for machine callers, and the decoded ``token``
payload for handlers that need a raw claim.

It is a plain pydantic model with no product-specific governance fields; a
generating project that needs richer claims subclasses or wraps it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class User(BaseModel):
    """An authenticated principal, hydrated from a verified token."""

    id: str
    username: str
    email: str
    first_name: str
    last_name: str
    roles: list[str]
    customer_id: str
    org_id: str | None = None
    service_account: bool = False
    token: dict[str, Any]
