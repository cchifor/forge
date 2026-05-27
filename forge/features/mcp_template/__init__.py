"""MCP server template via weld-mcp-template."""
from __future__ import annotations
from forge.api import ForgeAPI

def register(api: ForgeAPI) -> None:
    from forge.features.mcp_template import options, fragments
    options.register_all(api)
    fragments.register_all(api)
