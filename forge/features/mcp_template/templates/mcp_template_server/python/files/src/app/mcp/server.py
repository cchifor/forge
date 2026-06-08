"""Build the MCP server ASGI app.

A single :func:`build_server` call (vendored under :mod:`app.mcp._template`)
wires every registered plugin into the standard streamable-HTTP MCP
endpoint. The context resolver bridges this service's auth/correlation
context into each plugin invocation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.mcp._template import PluginContextResolver, build_server
from app.mcp.plugins import default_plugins

if TYPE_CHECKING:
    from starlette.applications import Starlette


def build_mcp_app(context_resolver: PluginContextResolver) -> Starlette:
    return build_server(
        default_plugins(),
        context_resolver=context_resolver,
    )
