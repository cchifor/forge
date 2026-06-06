"""Connector ABC + shared types (vendored, self-contained).

A :class:`Connector` reads or writes records against an external system.
Concrete implementations live under :mod:`app.connectors.builtin` and are
wired into :class:`~app.connectors.registry.ConnectorRegistry` at process
start.

The contract is intentionally small:

* :meth:`iter_records` — source-side: yields pages of records along with
  an opaque cursor. A caller persists the cursor between pages so a retry
  resumes from where the prior attempt stopped.
* :meth:`write_records` — sink-side: writes a batch and returns a
  :class:`WriteResult`. Idempotent under the same ``idempotency_key``
  when the underlying system supports it.
* :meth:`healthcheck` — optional liveness probe.

Configuration is split: ``ConfigModel`` is plain Pydantic (URL, table
name, paths, etc.); ``SecretsModel`` is optional and resolved at runtime
from your secrets layer so credentials never live in workflow JSON.

Vendored from the platform connector framework — imports only the stdlib
and pydantic (a base-template dependency).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

ConnectorCapability = Literal["read", "write", "both"]


class ConnectorError(RuntimeError):
    """Raised by connector implementations on persistent failure.

    Transient failures (timeouts, 5xx) should propagate the original
    httpx / sqlalchemy exception so the caller's error-categorization
    layer maps them to a transient outcome.
    """


class ConnectorPage(BaseModel):
    """One page of a streamed read."""

    records: list[dict[str, Any]]
    cursor: dict[str, Any] | None = None
    done: bool = False


class WriteResult(BaseModel):
    """Outcome of a single :meth:`Connector.write_records` call."""

    written: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ConnectorHealth(BaseModel):
    """Snapshot returned by :meth:`Connector.healthcheck`."""

    healthy: bool
    detail: str | None = None


class ConnectorInfo(BaseModel):
    """Public metadata describing a connector (e.g. for an info endpoint)."""

    name: str
    display_name: str
    description: str | None = None
    capabilities: ConnectorCapability
    config_schema: dict[str, Any]
    secrets_schema: dict[str, Any] | None = None


class Connector(ABC):
    """Pluggable read/write adapter for an external system.

    Subclasses declare ``name``, ``display_name``, ``ConfigModel``,
    optional ``SecretsModel``, and ``capabilities``. Methods that don't
    apply (e.g. :meth:`write_records` on a read-only source) should raise
    :class:`NotImplementedError` — :meth:`describe` reports the capability
    so callers don't dispatch unsupported ops.
    """

    name: ClassVar[str]
    display_name: ClassVar[str] = ""
    capabilities: ClassVar[ConnectorCapability] = "both"
    ConfigModel: ClassVar[type[BaseModel]]
    SecretsModel: ClassVar[type[BaseModel] | None] = None

    def __init__(
        self,
        config: BaseModel,
        secrets: BaseModel | None = None,
    ) -> None:
        self._config = config
        self._secrets = secrets

    @property
    def config(self) -> BaseModel:
        return self._config

    @property
    def secrets(self) -> BaseModel | None:
        return self._secrets

    async def iter_records(
        self,
        cursor: dict[str, Any] | None = None,
    ) -> AsyncIterator[ConnectorPage]:
        """Yield pages of records. Source connectors override this."""
        raise NotImplementedError(f"{type(self).__name__} does not support iter_records")
        if False:
            yield  # pragma: no cover — async-generator typing

    async def write_records(
        self,
        records: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> WriteResult:
        """Write a batch. Sink connectors override this."""
        raise NotImplementedError(f"{type(self).__name__} does not support write_records")

    async def healthcheck(self) -> ConnectorHealth:
        """Best-effort liveness check. Default: always healthy."""
        return ConnectorHealth(healthy=True)

    @classmethod
    def describe(cls) -> ConnectorInfo:
        """Build the public metadata row for this connector."""
        return ConnectorInfo(
            name=cls.name,
            display_name=cls.display_name or cls.name,
            description=cls.__doc__,
            capabilities=cls.capabilities,
            config_schema=cls.ConfigModel.model_json_schema(),
            secrets_schema=(
                cls.SecretsModel.model_json_schema() if cls.SecretsModel is not None else None
            ),
        )

    @abstractmethod
    def __repr__(self) -> str: ...  # encourages subclasses to give a useful repr
