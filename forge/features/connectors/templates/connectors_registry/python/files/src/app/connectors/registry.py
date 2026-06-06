"""Connector registry (vendored, self-contained).

In-process container that maps a connector ``name`` → implementation
class. Used to instantiate a connector from config/secrets at run time
and to enumerate the available connectors for an info endpoint / UI.

The registry is decoupled from imports so handlers don't accidentally
trigger circular loads. Instances are stateless from the registry's
perspective — every invocation creates a fresh connector with the
caller's config and secrets.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from app.connectors.base import Connector, ConnectorInfo


class ConnectorRegistryError(ValueError):
    """Raised when a connector lookup or config validation fails."""


class ConnectorRegistry:
    """In-process registry of connector classes."""

    def __init__(self) -> None:
        self._connectors: dict[str, type[Connector]] = {}

    def register(self, cls: type[Connector]) -> None:
        name = getattr(cls, "name", None)
        if not name:
            raise ConnectorRegistryError(f"{cls.__name__} missing class-level `name`")
        self._connectors[name] = cls

    def names(self) -> list[str]:
        return sorted(self._connectors)

    def get(self, name: str) -> type[Connector]:
        cls = self._connectors.get(name)
        if cls is None:
            raise ConnectorRegistryError(f"no connector registered for {name!r}")
        return cls

    def describe(self) -> list[ConnectorInfo]:
        return [
            cls.describe()
            for cls in sorted(
                self._connectors.values(),
                key=lambda c: c.name,
            )
        ]

    def build(
        self,
        name: str,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any] | None = None,
    ) -> Connector:
        """Instantiate a connector with validated config + secrets."""
        cls = self.get(name)
        try:
            cfg_model = cls.ConfigModel.model_validate(config or {})
        except ValidationError as exc:
            raise ConnectorRegistryError(f"invalid config for connector {name!r}: {exc}") from exc
        secrets_model: BaseModel | None = None
        if cls.SecretsModel is not None and secrets:
            try:
                secrets_model = cls.SecretsModel.model_validate(secrets)
            except ValidationError as exc:
                raise ConnectorRegistryError(
                    f"invalid secrets for connector {name!r}: {exc}"
                ) from exc
        return cls(cfg_model, secrets_model)


def build_default_connector_registry(
    *,
    enable_http: bool = False,
    enable_fs: bool = False,
    enable_sql: bool = False,
    enable_s3: bool = False,
    enable_sample: bool = False,
) -> ConnectorRegistry:
    """Build a registry populated with the selected built-in connectors.

    Each builtin is gated behind a flag so a service only registers the
    connectors whose dependencies it actually installed (``http`` needs
    httpx — a base dependency; ``s3`` needs boto3; ``sql`` needs an async
    SQLAlchemy driver). The :mod:`app.connectors.builtin` package catches
    ``ImportError`` per connector, so an enabled-but-uninstalled builtin
    is skipped rather than crashing boot.
    """
    from app.connectors import builtin as _builtin

    selected: list[str] = []
    if enable_http:
        selected.append("HTTPConnector")
    if enable_fs:
        selected.append("FilesystemConnector")
    if enable_sql:
        selected.append("SQLConnector")
    if enable_s3:
        selected.append("S3Connector")
    if enable_sample:
        selected.append("SampleConnector")

    registry = ConnectorRegistry()
    for name in selected:
        cls = getattr(_builtin, name, None)
        if cls is not None:
            registry.register(cls)
    return registry
