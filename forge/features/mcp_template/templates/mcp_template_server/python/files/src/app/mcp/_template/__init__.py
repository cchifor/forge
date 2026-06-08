"""Vendored MCP-server template — weld-free, self-contained.

Build a first-party MCP server for one or more plugins with minimal
boilerplate::

    from app.mcp._template import BasePlugin, PluginContext, ToolDef, build_server

    class MyPlugin(BasePlugin):
        slug = "com.example.service"

        async def list_tools(self, ctx: PluginContext) -> list[ToolDef]:
            return [ToolDef(name="ping", description="Ping",
                            input_schema={"type": "object", "properties": {}},
                            handler=self._ping)]

        async def _ping(self, args: dict, ctx: PluginContext) -> dict:
            return {"ok": True}

    app = build_server(MyPlugin(), context_resolver=...)

The server exposes a standard streamable-HTTP MCP endpoint per plugin.
``tenant_id`` is optional, so single-tenant services work out of the box.
Imports only the official ``mcp`` library + starlette + httpx (and
optionally opentelemetry / prometheus / PyYAML) — never a private SDK.
"""

from __future__ import annotations

from app.mcp._template.errors import (
    AuthError,
    NotFoundError,
    PluginError,
    UpstreamError,
    map_to_mcp_error,
)
from app.mcp._template.openapi import AuthConfig, openapi_to_tools
from app.mcp._template.plugin import (
    BasePlugin,
    IntegrationPlugin,
    PluginContext,
    PluginContextResolver,
    ToolDef,
)
from app.mcp._template.server import build_server
from app.mcp._template.telemetry import metrics_asgi_app

__all__ = [
    "AuthConfig",
    "AuthError",
    "BasePlugin",
    "IntegrationPlugin",
    "NotFoundError",
    "PluginContext",
    "PluginContextResolver",
    "PluginError",
    "ToolDef",
    "UpstreamError",
    "build_server",
    "map_to_mcp_error",
    "metrics_asgi_app",
    "openapi_to_tools",
]
