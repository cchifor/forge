"""Service-local connector registry.

Re-exports the registry builder so handlers obtain adapters with::

    registry = container.get(ConnectorRegistry)
    http = registry.get("http", base_url=...)
"""

from __future__ import annotations

from app.connectors.registry import build_connector_registry

__all__ = ["build_connector_registry"]
