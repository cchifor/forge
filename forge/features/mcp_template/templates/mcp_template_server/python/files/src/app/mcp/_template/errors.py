"""Error types + mapping to MCP error responses (vendored).

Plugins raise domain-specific exceptions; the server wraps them so the
MCP client gets a structured error instead of a stack trace.

Vendored, self-contained: pure stdlib.
"""

from __future__ import annotations


class PluginError(Exception):
    """Base class for plugin-raised errors the server should surface."""

    def __init__(self, message: str, *, code: str = "plugin_error") -> None:
        super().__init__(message)
        self.code = code


class AuthError(PluginError):
    """Credentials are missing, invalid, or expired."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="auth_error")


class UpstreamError(PluginError):
    """Upstream API returned an error (4xx/5xx)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message, code="upstream_error")
        self.status_code = status_code


class NotFoundError(PluginError):
    """Requested resource does not exist."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="not_found")


def map_to_mcp_error(exc: Exception) -> dict:
    """Translate an exception into an MCP ``isError=true`` result payload.

    Returns a dict with a ``content`` list and ``isError=True`` suitable
    for assembling into a ``CallToolResult``. The MCP server stays
    responsive even when plugins fail.
    """
    if isinstance(exc, PluginError):
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"[{exc.code}] {exc}"}],
        }
    return {
        "isError": True,
        "content": [{"type": "text", "text": f"[internal_error] {type(exc).__name__}: {exc}"}],
    }
