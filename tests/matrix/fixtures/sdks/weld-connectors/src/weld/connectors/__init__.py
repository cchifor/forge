"""weld.connectors stub."""
from typing import Any


class ConnectorRegistry:
    """Stub connector registry."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._connectors: dict[str, Any] = {}

    def register(self, name: str, connector: Any) -> None:
        self._connectors[name] = connector

    def get(self, name: str) -> Any:
        return self._connectors.get(name)


def build_default_connector_registry(*args: Any, **kwargs: Any) -> ConnectorRegistry:
    return ConnectorRegistry()
