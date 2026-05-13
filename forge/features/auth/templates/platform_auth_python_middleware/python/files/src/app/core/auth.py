"""Identity helpers for the integration service.

After the platform-auth migration, identity comes from the verified
bearer token (set by :class:`AuthContextMiddleware` on
``request.state.identity``); the legacy ``X-Gatekeeper-*`` plain-header
trust path is gone. The helpers below preserve the same call-sites as
before but read from the verified context.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from weld.core.domain.account import Account
from weld.core.domain.user import User

logger = logging.getLogger(__name__)


def get_gatekeeper_user(request: Request) -> User:
    """Extract the verified user identity from ``request.state``.

    Name preserved for back-compat with existing call sites; the
    underlying source of truth is now the bearer token.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return user


def get_tenant_id(request: Request) -> str:
    """Return the tenant ID as a string (UUID stringified).

    Returned as a string for compatibility with call sites that store it
    in URL paths or headers without conversion. Repositories that need a
    proper UUID should consume :class:`platform_auth.IdentityContext`
    directly via ``request.state.identity.tenant_id``.
    """
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return str(identity.tenant_id)


def get_account(request: Request) -> Account:
    """Build an :class:`Account` from the verified identity."""
    user = get_gatekeeper_user(request)
    return Account(customer_id=user.customer_id, user_id=user.id)
