"""``weld.mcp_template.openapi`` stub."""

from dataclasses import dataclass
from typing import Any


@dataclass
class AuthConfig:
    """Stub auth config for the OpenAPI codegen path."""

    scheme: str = "bearer"
    audience: str = ""


def openapi_to_tools(*args: Any, **kwargs: Any) -> list[Any]:
    """Stub. Real impl walks an OpenAPI doc and emits MCP tool defs."""
    return []
