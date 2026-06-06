"""Plugin contract (vendored, self-contained).

An :class:`IntegrationPlugin` is the minimum a plugin must implement. It
declares its tools and handles calls. Everything else — FastMCP
boilerplate, per-request context resolution, OTel spans, error mapping —
is handled by :func:`app.mcp._template.server.build_server`.

The host application supplies a :class:`PluginContextResolver` that turns
an incoming request (headers + query params) into a
:class:`PluginContext`.

Vendored, self-contained: imports only the stdlib + httpx.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx


@dataclass
class ToolDef:
    """A single MCP tool exposed by a plugin.

    ``handler`` is the async callable invoked on ``tools/call``. It
    receives the MCP arguments dict plus the per-request
    :class:`PluginContext` and returns a JSON-serialisable result. The
    server wraps it in MCP's content envelope (text by default).
    """

    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict, "PluginContext"], Awaitable[Any]]
    annotations: dict = field(default_factory=dict)


@dataclass
class PluginContext:
    """Per-request context passed to a plugin's list_tools / call_tool.

    ``credentials`` is the secrets dict for the caller (e.g.
    ``{"api_key": "...", "subdomain": "acme"}``). ``tenant_id`` and
    ``user_id`` are OPTIONAL — a single-tenant service can leave them
    ``None`` and the server still functions; multi-tenant hosts populate
    them so telemetry spans carry the tenant/integration dimensions.
    """

    credentials: dict[str, Any]
    http: httpx.AsyncClient
    tenant_id: str | None = None
    user_id: str | None = None
    integration_id: str | None = None
    slug: str | None = None
    refresh_oauth: Callable[[], Awaitable[str]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IntegrationPlugin(Protocol):
    """The plugin contract.

    ``slug`` is the plugin identifier used in MCP tool namespacing
    (reverse-DNS per the MCP spec).
    """

    slug: str

    async def list_tools(self, ctx: PluginContext) -> list[ToolDef]:
        """Return the tool list for this caller.

        Called on every MCP ``tools/list`` request. Implementations can
        return a fixed list or vary it based on ``ctx.credentials`` /
        ``ctx.extra``.
        """
        ...

    async def call_tool(self, name: str, args: dict, ctx: PluginContext) -> Any:
        """Dispatch a tool call.

        The :class:`BasePlugin` default looks the tool up by name in
        ``list_tools`` and invokes its ``handler``.
        """
        ...


class BasePlugin:
    """Convenience base class: default ``call_tool`` dispatches by name.

    Plugins that don't need custom dispatch logic inherit from this and
    only implement ``list_tools``.
    """

    slug: str = ""

    async def list_tools(self, ctx: PluginContext) -> list[ToolDef]:
        raise NotImplementedError

    async def call_tool(self, name: str, args: dict, ctx: PluginContext) -> Any:
        tools = await self.list_tools(ctx)
        for tool in tools:
            if tool.name == name:
                return await tool.handler(args, ctx)
        raise KeyError(f"Unknown tool: {name}")


PluginContextResolver = Callable[
    [dict[str, str]],
    Awaitable[PluginContext],
]
"""Async callable the host supplies. Given the incoming request's headers
merged with query-string params, return a :class:`PluginContext`. Raises
:class:`~app.mcp._template.errors.AuthError` on identity failure.
"""
