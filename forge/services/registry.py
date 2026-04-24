"""Capability → docker-compose service registry.

A *service* is a container that the generated docker-compose stack
spins up alongside the application backend(s): redis, qdrant, a vector
store sidecar, a webhook relay, an LLM proxy. Before this registry,
every such service was hardcoded in
``forge/templates/deploy/docker-compose.yml.j2`` with an ``{% if X %}``
block. Adding a new backend required editing the template — a hard
ceiling on plugin extensibility.

This module defines :class:`ServiceTemplate` — a plain declaration of
how a service renders into docker-compose — and a registry keyed by
*capability*. Fragments that produce a capability (see
:class:`forge.fragments.Fragment.capabilities`) can register a matching
service; the renderer walks the registry once per generation and
emits every service whose capability appears in the resolved plan.

Plugins register via ``ForgeAPI.add_service(capability, template)``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ServiceTemplate:
    """Docker-compose service declaration keyed by capability.

    The fields map one-to-one onto the ``services.<name>`` block of
    docker-compose v3. ``extra`` captures any additional top-level key
    (e.g. ``deploy``, ``profiles``) without pinning the schema.

    The rendered block looks like::

        <name>:
          image: <image>
          command: <command...>
          environment:
            KEY: value
          ports:
            - "<host>:<container>"
          volumes:
            - <volume>:/path
          healthcheck: {...}
          depends_on: {...}
          networks: [app-network]
    """

    name: str
    image: str
    command: list[str] | None = None
    environment: dict[str, str] = field(default_factory=dict)
    ports: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    healthcheck: dict[str, Any] | None = None
    depends_on: dict[str, dict[str, str]] = field(default_factory=dict)
    networks: tuple[str, ...] = ("app-network",)
    restart: str = "unless-stopped"
    extra: dict[str, Any] = field(default_factory=dict)

    # Named volumes this service declares on the top-level ``volumes:`` key.
    # Rendered alongside the service itself so the compose file is
    # self-contained.
    named_volumes: tuple[str, ...] = ()

    def as_compose_dict(self) -> dict[str, Any]:
        """Flatten into the dict docker-compose expects."""
        out: dict[str, Any] = {"image": self.image}
        if self.command:
            out["command"] = list(self.command)
        if self.environment:
            out["environment"] = dict(self.environment)
        if self.ports:
            out["ports"] = list(self.ports)
        if self.volumes:
            out["volumes"] = list(self.volumes)
        if self.healthcheck:
            out["healthcheck"] = dict(self.healthcheck)
        if self.depends_on:
            out["depends_on"] = {k: dict(v) for k, v in self.depends_on.items()}
        if self.networks:
            out["networks"] = list(self.networks)
        if self.restart:
            out["restart"] = self.restart
        for key, value in self.extra.items():
            out[key] = value
        return out


SERVICE_REGISTRY: dict[str, ServiceTemplate] = {}


def register_service(capability: str, template: ServiceTemplate) -> None:
    """Register a service template keyed by capability.

    ``capability`` matches the ``Fragment.capabilities`` string — when a
    fragment with that capability appears in the resolved plan, the
    service is emitted into ``docker-compose.yml``.

    Re-registering a capability with a different template raises to
    catch two fragments silently claiming the same service name. Re-
    registering with an identical template is a no-op (supports plugin
    reload in tests).
    """
    existing = SERVICE_REGISTRY.get(capability)
    if existing is not None and existing != template:
        raise ValueError(
            f"Service capability '{capability}' is already registered with a "
            f"different template (name={existing.name}, image={existing.image}); "
            f"refusing re-register as (name={template.name}, image={template.image})."
        )
    SERVICE_REGISTRY[capability] = template


def get_services_for_capabilities(
    capabilities: Iterable[str],
) -> list[ServiceTemplate]:
    """Return the registered ServiceTemplates for a set of capabilities.

    Ordering follows input iteration; deduplication preserves first
    occurrence. Unknown capabilities (no matching registration) are
    silently skipped — not every capability corresponds to a sidecar
    service.
    """
    out: list[ServiceTemplate] = []
    seen: set[str] = set()
    for cap in capabilities:
        template = SERVICE_REGISTRY.get(cap)
        if template is None or template.name in seen:
            continue
        seen.add(template.name)
        out.append(template)
    return out


def reset_for_tests() -> None:
    """Clear the registry. Call in pytest fixtures that exercise plugin load."""
    SERVICE_REGISTRY.clear()
