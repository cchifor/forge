"""Service-local MCP server.

Exports :func:`build_mcp_app` which the main FastAPI app mounts on
``/mcp``. Add new integrations by registering more :class:`IntegrationPlugin`
instances in :mod:`app.mcp.plugins`.
"""

from __future__ import annotations

from app.mcp.server import build_mcp_app

__all__ = ["build_mcp_app"]
