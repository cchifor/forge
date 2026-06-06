"""Build an MCP streamable-HTTP server from one or more plugins (vendored).

Returns a Starlette application that hosts every supplied plugin, each
mounted under ``/<plugin.slug>``. A shared lifespan drives each plugin's
FastMCP session manager.

Per request, a :class:`PluginContext` is resolved from the incoming
headers + query string and stashed in a contextvar the handlers read.
``tenant_id`` is optional — single-tenant hosts can resolve a context
without one.

Vendored, self-contained: imports the official ``mcp`` library + starlette
(both fragment-declared) plus the stdlib. No private SDKs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import parse_qsl

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from app.mcp._template.errors import AuthError, PluginError, map_to_mcp_error
from app.mcp._template.plugin import (
    IntegrationPlugin,
    PluginContext,
    PluginContextResolver,
)
from app.mcp._template.telemetry import list_tools_span, tool_call_span

log = logging.getLogger(__name__)

_current_ctx: ContextVar[PluginContext | None] = ContextVar(
    "app.mcp_current_ctx", default=None
)


def _serialise(result: Any) -> list[TextContent]:
    """Convert a plugin's return value into MCP ``content`` items.

    Strings pass through; anything else is JSON-encoded. Plugins that
    need richer media types should return the raw MCP content list.
    """
    if isinstance(result, list) and all(
        isinstance(item, dict) and "type" in item for item in result
    ):
        return [TextContent(**item) if item["type"] == "text" else item for item in result]
    if isinstance(result, str):
        return [TextContent(type="text", text=result)]
    return [TextContent(type="text", text=json.dumps(result, default=str))]


def _build_fastmcp(
    plugin: IntegrationPlugin,
    *,
    context_resolver: PluginContextResolver,
    name: str | None = None,
    instructions: str | None = None,
) -> tuple[FastMCP, Callable[[Scope, Receive, Send], Awaitable[None]]]:
    """Construct a FastMCP + a context-resolving ASGI wrapper for one plugin."""
    server_name = name or plugin.slug
    mcp = FastMCP(
        server_name,
        instructions=instructions or f"Plugin: {plugin.slug}",
        stateless_http=True,
        # Hosts typically reach plugins via an internal hostname; FastMCP's
        # default DNS-rebinding protection would reject non-localhost Host
        # headers with 421. Disable it here and let the host's own auth /
        # network policy gate access.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    low = mcp._mcp_server

    @low.list_tools()
    async def _list_tools() -> list[Tool]:
        ctx = _current_ctx.get()
        if ctx is None:
            return []
        with list_tools_span(
            slug=plugin.slug,
            tenant_id=ctx.tenant_id,
            integration_id=ctx.integration_id,
        ):
            defs = await plugin.list_tools(ctx)
        return [
            Tool(
                name=d.name,
                description=d.description,
                inputSchema=d.input_schema,
            )
            for d in defs
        ]

    @low.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        ctx = _current_ctx.get()
        if ctx is None:
            return [TextContent(type="text", text="[auth_error] missing plugin context")]
        with tool_call_span(
            slug=plugin.slug,
            tool_name=name,
            tenant_id=ctx.tenant_id,
            integration_id=ctx.integration_id,
        ):
            try:
                result = await plugin.call_tool(name, arguments or {}, ctx)
                return _serialise(result)
            except (PluginError, Exception) as exc:  # noqa: BLE001
                log.warning("plugin %r tool %r failed: %s", plugin.slug, name, exc)
                payload = map_to_mcp_error(exc)
                return [TextContent(**c) for c in payload["content"]]

    inner = mcp.streamable_http_app()

    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return
        raw_headers = {
            h[0].decode("latin-1").lower(): h[1].decode("latin-1")
            for h in scope.get("headers", [])
        }
        query = dict(parse_qsl(scope.get("query_string", b"").decode("utf-8")))
        merged = {**raw_headers, **query}
        try:
            ctx = await context_resolver(merged)
        except AuthError as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        token = _current_ctx.set(ctx)
        try:
            await inner(scope, receive, send)
        finally:
            _current_ctx.reset(token)

    return mcp, asgi


def build_server(
    plugins: IntegrationPlugin | tuple[IntegrationPlugin, ...] | list[IntegrationPlugin],
    *,
    context_resolver: PluginContextResolver,
    instructions: str | None = None,
) -> Starlette:
    """Construct a streamable-HTTP MCP server for one or more plugins.

    ``plugins`` accepts a single plugin or a sequence. Each plugin is
    mounted under ``/<plugin.slug>`` in the returned Starlette app. A
    shared lifespan enters every plugin's FastMCP session manager (which
    owns the anyio task group the streamable-HTTP transport needs).

    ``context_resolver`` receives a dict built from request headers merged
    with query parameters and must return a :class:`PluginContext` or
    raise :class:`AuthError`.
    """
    plugin_list: list[IntegrationPlugin]
    if isinstance(plugins, (tuple, list)):
        plugin_list = list(plugins)
    else:
        plugin_list = [plugins]

    fastmcps: list[FastMCP] = []
    routes: list[Mount] = []
    for plugin in plugin_list:
        mcp, asgi = _build_fastmcp(
            plugin,
            context_resolver=context_resolver,
            instructions=instructions,
        )
        fastmcps.append(mcp)
        routes.append(Mount(f"/{plugin.slug}", app=asgi))

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for mcp in fastmcps:
                await stack.enter_async_context(mcp.session_manager.run())
            yield

    return Starlette(routes=routes, lifespan=lifespan)
