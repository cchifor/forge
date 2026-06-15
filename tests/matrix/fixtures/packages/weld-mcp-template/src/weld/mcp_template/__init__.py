"""weld.mcp_template stub."""

from typing import Any


class BasePlugin:
    """Stub base for MCP plugins."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...


class IntegrationPlugin(BasePlugin):
    """Stub integration-style plugin."""


class PluginContext:
    """Stub plugin context."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...


class PluginContextResolver:
    """Stub context resolver."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def resolve(self, *args: Any, **kwargs: Any) -> PluginContext:
        return PluginContext()


class ToolDef:
    """Stub MCP tool definition."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...


def build_server(*args: Any, **kwargs: Any) -> Any:
    """Stub MCP server builder."""
    return None
