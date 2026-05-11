"""``mcp.*`` — MCP server template via weld-mcp-template.

Scaffolds a lite MCP server inside the service for first-party SaaS
integrations. Each integration is an :class:`IntegrationPlugin` that
registers tools; :func:`build_server` exposes the standard streamable-
HTTP MCP endpoint that the platform gateway connects to.

Python-only — weld-mcp-template is Python-only.
"""

from __future__ import annotations

from forge.features.mcp_template import (  # noqa: F401, E402
    fragments,
    options,
)
