"""Default :class:`PluginContextResolver` for the mounted MCP server.

The host application supplies a resolver that turns an incoming request's
headers + query params into a :class:`PluginContext`. This module ships a
sensible single-tenant default so the ``/mcp`` mount works out of the box:
it hands every plugin call a shared :class:`httpx.AsyncClient` and an empty
credentials dict, reading an optional ``x-tenant-id`` header into
``tenant_id`` when present.

Replace :func:`build_default_context_resolver` (or pass your own resolver
to :func:`app.mcp.build_mcp_app`) once the service has real per-caller
auth/credentials wiring — e.g. resolve a bearer token to a tenant +
upstream API key. The default never raises :class:`AuthError`, so it is
appropriate for local/dev and single-tenant deployments only.

Vendored, self-contained: imports only the stdlib + httpx + the sibling
``_template`` contract.
"""

from __future__ import annotations

import httpx

from app.mcp._template import PluginContext, PluginContextResolver

# One client per process, shared across MCP calls. The mount is created
# once at app construction, so this lives for the app's lifetime; the
# default server lifespan does not close it (it owns no client) — fine for
# a process-lifetime singleton.
_HTTP = httpx.AsyncClient()


def build_default_context_resolver() -> PluginContextResolver:
    """Return a single-tenant default resolver.

    Given the merged request headers + query params, build a
    :class:`PluginContext` with empty credentials and the shared HTTP
    client. ``tenant_id`` is read from ``x-tenant-id`` when present so a
    multi-tenant caller still surfaces the dimension in telemetry.
    """

    async def _resolve(request: dict[str, str]) -> PluginContext:
        return PluginContext(
            credentials={},
            http=_HTTP,
            tenant_id=request.get("x-tenant-id"),
        )

    return _resolve
