"""Service-local connector registry (vendored, weld-free).

Re-exports the registry builder + the core registry types so handlers
obtain adapters with::

    registry = container.get(ConnectorRegistry)
    http = registry.build("http", config={"url": "https://api..."})

The connector framework (ABC, registry, sync runner, builtins) is
vendored under :mod:`app.connectors` and imports only the stdlib +
pydantic / httpx / sqlalchemy from the base template — no private SDKs.
"""

from __future__ import annotations

from app.connectors._service import build_connector_registry
from app.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorHealth,
    ConnectorInfo,
    ConnectorPage,
    WriteResult,
)
from app.connectors.registry import (
    ConnectorRegistry,
    ConnectorRegistryError,
)
from app.connectors.runner import (
    BatchResult,
    SyncDirection,
    SyncRunner,
)

__all__ = [
    "BatchResult",
    "Connector",
    "ConnectorError",
    "ConnectorHealth",
    "ConnectorInfo",
    "ConnectorPage",
    "ConnectorRegistry",
    "ConnectorRegistryError",
    "SyncDirection",
    "SyncRunner",
    "WriteResult",
    "build_connector_registry",
]
