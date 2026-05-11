"""Build the MCP server ASGI app.

A single :func:`weld.mcp_template.build_server` call wires every
registered plugin into the standard streamable-HTTP MCP endpoint. The
context resolver bridges the platform's auth/correlation context into
each plugin invocation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weld.mcp_template import PluginContextResolver, build_server

from app.mcp.plugins import default_plugins

if TYPE_CHECKING:
    from starlette.applications import Starlette


def build_mcp_app(context_resolver: PluginContextResolver) -> Starlette:
    return build_server(
        plugins=default_plugins(),
        context_resolver=context_resolver,
    )
