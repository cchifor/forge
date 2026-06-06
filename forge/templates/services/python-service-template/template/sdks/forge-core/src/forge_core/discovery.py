"""Eureka service-discovery registration.

A thin wrapper around ``py_eureka_client`` exposing the bits a service uses
at lifespan: :meth:`Discovery.register_async` / :meth:`unregister_async`
(the production async path) plus the sync variants.

``py-eureka-client`` is an *optional* runtime dependency: not every service
enables discovery, so forge-core does not declare it. A service that turns
discovery on declares ``py-eureka-client`` in its own ``pyproject.toml``;
forge-core imports it lazily so the module remains importable (and the rest
of forge-core remains testable) in an environment where the client is not
installed. The import is resolved on first registration — turning discovery
on without the client installed fails loudly there, rather than at import
time for every consumer.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import py_eureka_client.eureka_client as _EurekaClientModule


def _eureka_client() -> _EurekaClientModule:
    """Import and return the ``py_eureka_client`` module, lazily.

    Raises a clear :class:`RuntimeError` (rather than a bare
    ``ModuleNotFoundError``) when discovery is used without the optional
    ``py-eureka-client`` dependency installed.
    """
    try:
        return importlib.import_module("py_eureka_client.eureka_client")
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via monkeypatch
        raise RuntimeError(
            "Service discovery is enabled but 'py-eureka-client' is not "
            "installed. Add it to your project dependencies."
        ) from exc


class Discovery:
    """A registrable Eureka service instance."""

    def __init__(
        self,
        app_name: Any,
        service_url: Any,
        service_port: Any,
        service_user: Any,
        service_password: Any,
        instance_ip: Any,
        instance_host: Any,
        instance_port: Any,
        **kwargs: Any,
    ) -> None:
        self.app_name = app_name
        self.service_url = service_url
        self.service_port = service_port
        self.service_user = service_user
        self.service_password = service_password
        self.instance_ip = instance_ip
        self.instance_host = instance_host
        self.instance_port = instance_port
        # Hold a reference to the fire-and-forget registration task so it is
        # not garbage-collected before it runs to completion.
        self._register_task: asyncio.Task[None] | None = None

    def register(self) -> None:
        _eureka_client().init(
            eureka_server=self.service_url,
            app_name=self.app_name,
            instance_port=self.service_port,
            eureka_basic_auth_user=self.service_user,
            eureka_basic_auth_password=self.service_password,
        )

    def unregister(self) -> None:
        _eureka_client().stop()

    async def register_async(self) -> None:
        self._register_task = asyncio.create_task(
            _eureka_client().init_async(
                eureka_server=self.service_url,
                app_name=self.app_name,
                eureka_basic_auth_user=self.service_user,
                eureka_basic_auth_password=self.service_password,
                instance_ip=self.instance_ip,
                instance_host=self.instance_host,
                instance_port=self.instance_port,
            )
        )

    async def unregister_async(self) -> None:
        await _eureka_client().stop_async()

    def __str__(self) -> str:
        return (
            f"Discovery(app_name={self.app_name}, "
            f"service_url={self.service_url}, "
            f"instance_host={self.instance_host}, "
            f"instance_port={self.instance_port})"
        )
