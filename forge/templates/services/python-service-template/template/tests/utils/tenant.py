"""Tenant-context builders used in unit + integration tests.

Mirrored across the three forge backends — see
``docs/testing-generated-backends.md`` for the cross-language
contract. Tests should depend on these helpers rather than building
``TenantContext`` instances or HTTP headers from scratch so a future
change to the tenant model surfaces in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_CUSTOMER_ID = DEFAULT_USER_ID
DEFAULT_EMAIL = "test@localhost"
DEFAULT_ROLES = ("user",)


@dataclass(frozen=True)
class TenantTestContext:
    """Plain record of the fields tests typically vary."""

    user_id: str = DEFAULT_USER_ID
    customer_id: str = DEFAULT_CUSTOMER_ID
    email: str = DEFAULT_EMAIL
    roles: tuple[str, ...] = DEFAULT_ROLES


def tenant_factory(
    *,
    user_id: str = DEFAULT_USER_ID,
    customer_id: str | None = None,
    email: str = DEFAULT_EMAIL,
    roles: tuple[str, ...] = DEFAULT_ROLES,
) -> TenantTestContext:
    """Build a :class:`TenantTestContext`.

    ``customer_id`` defaults to ``user_id`` so single-tenant tests can
    pass just ``user_id``. Pass ``customer_id="other-tenant"`` to
    exercise cross-tenant isolation.
    """
    return TenantTestContext(
        user_id=user_id,
        customer_id=customer_id or user_id,
        email=email,
        roles=roles,
    )


def authenticated_headers(ctx: TenantTestContext | None = None) -> dict[str, str]:
    """Header dict that simulates Gatekeeper having authenticated the request.

    Used by integration tests that call the FastAPI app via TestClient.
    The global tenant-extraction middleware will read these and
    populate ``request.state.tenant``.
    """
    if ctx is None:
        ctx = tenant_factory()
    headers = {
        "x-gatekeeper-user-id": ctx.user_id,
        "x-gatekeeper-email": ctx.email,
        "x-gatekeeper-roles": ",".join(ctx.roles),
    }
    if ctx.customer_id != ctx.user_id:
        headers["x-customer-id"] = ctx.customer_id
    return headers
