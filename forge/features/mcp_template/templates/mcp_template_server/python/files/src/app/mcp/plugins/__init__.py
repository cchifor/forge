"""MCP integration plugins.

Each plugin is an :class:`IntegrationPlugin` exposing a set of tools
to MCP clients. Register additional plugins by appending to the
``default_plugins()`` tuple.
"""

from __future__ import annotations

from weld.mcp_template import IntegrationPlugin

from app.mcp.plugins.ping import PingPlugin


def default_plugins() -> tuple[IntegrationPlugin, ...]:
    return (PingPlugin(),)


__all__ = ["default_plugins"]
