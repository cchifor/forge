"""Tenant context extraction middleware.

Reads tenant and user identity from gateway-injected headers
(X-Customer-ID, X-User-ID, X-Tenant-Slug) and stashes them on
request.state for downstream access by endpoints and repositories.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[..., Any]
    ) -> Response:
        request.state.customer_id = request.headers.get("x-customer-id")
        request.state.user_id = request.headers.get("x-user-id")
        request.state.tenant_slug = request.headers.get("x-tenant-slug")
        return await call_next(request)
