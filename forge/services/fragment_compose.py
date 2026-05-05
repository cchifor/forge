"""Fragment-shipped ``compose.yaml`` loader (P1.3, 1.1.0-alpha.2).

Lets a fragment declare a docker-compose sidecar service via a YAML
file alongside its per-language directories instead of writing Python
that constructs a :class:`forge.services.registry.ServiceTemplate`.
The generator walks the resolved plan, reads each fragment's
``compose.yaml`` (if present), and registers the service into
:data:`forge.services.registry.SERVICE_REGISTRY` so
``forge.docker_manager.render_compose`` picks it up via the existing
capability → service map.

Layout the loader expects::

    forge/templates/_fragments/<name>/
    ├── compose.yaml          <-- this file (language-agnostic)
    ├── python/
    │   ├── files/
    │   ├── inject.yaml
    │   └── deps.yaml
    ├── node/ ...
    └── rust/ ...

The ``compose.yaml`` schema mirrors :class:`ServiceTemplate` field-for-
field. ``capability`` at the top level keys the registry; the rest of
the file is the service block. Existing imperative compose blocks in
``forge/templates/deploy/docker-compose.yml.j2`` keep working — this
is additive: fragments can opt in over time without forcing a big-bang
rewrite.

Schema (all fields optional unless marked required)::

    capability: <str>          # required, registry key
    service:                   # required
      name: <str>              # required, docker-compose service key
      image: <str>             # required, image:tag
      command: [<str>, ...]
      environment: {KEY: VALUE, ...}
      ports: ["<host>:<container>", ...]
      volumes: ["<src>:<dst>", ...]
      named_volumes: [<volume-name>, ...]
      healthcheck:
        test: ["CMD", ...]
        interval: 10s
        timeout: 3s
        retries: 5
      depends_on:
        <service>:
          condition: service_healthy
      networks: [app-network]
      restart: unless-stopped
      extra: {<arbitrary-key>: <value>}
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from forge.services.registry import ServiceTemplate, register_service


class FragmentComposeError(ValueError):
    """Raised when a fragment's compose.yaml is malformed."""


def load_fragment_compose(
    fragment_root: Path,
) -> tuple[str, ServiceTemplate] | None:
    """Return ``(capability, ServiceTemplate)`` from ``fragment_root/compose.yaml``.

    Returns ``None`` when the file is absent (the common case — most
    fragments don't ship a sidecar). Raises :class:`FragmentComposeError`
    on malformed YAML or missing required keys so plan validation can
    surface the issue with the offending fragment named.
    """
    compose_path = fragment_root / "compose.yaml"
    if not compose_path.is_file():
        return None

    try:
        raw = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FragmentComposeError(f"{compose_path}: invalid YAML — {exc}") from exc

    if not isinstance(raw, dict):
        raise FragmentComposeError(
            f"{compose_path}: expected a top-level mapping with ``capability`` and ``service`` keys"
        )

    capability = raw.get("capability")
    if not isinstance(capability, str) or not capability.strip():
        raise FragmentComposeError(
            f"{compose_path}: top-level ``capability`` must be a non-empty string"
        )

    service_block = raw.get("service")
    if not isinstance(service_block, dict):
        raise FragmentComposeError(f"{compose_path}: top-level ``service`` must be a mapping")

    name = service_block.get("name")
    image = service_block.get("image")
    if not isinstance(name, str) or not name.strip():
        raise FragmentComposeError(f"{compose_path}: ``service.name`` must be a non-empty string")
    if not isinstance(image, str) or not image.strip():
        raise FragmentComposeError(f"{compose_path}: ``service.image`` must be a non-empty string")

    template = ServiceTemplate(
        name=name,
        image=image,
        command=list(service_block["command"])
        if "command" in service_block and service_block["command"]
        else None,
        environment={str(k): str(v) for k, v in (service_block.get("environment") or {}).items()},
        ports=[str(p) for p in (service_block.get("ports") or [])],
        volumes=[str(v) for v in (service_block.get("volumes") or [])],
        healthcheck=dict(service_block["healthcheck"])
        if service_block.get("healthcheck")
        else None,
        depends_on={str(k): dict(v) for k, v in (service_block.get("depends_on") or {}).items()},
        networks=tuple(service_block.get("networks") or ("app-network",)),
        restart=str(service_block.get("restart", "unless-stopped")),
        named_volumes=tuple(service_block.get("named_volumes") or ()),
        extra=dict(service_block.get("extra") or {}),
    )
    return capability, template


def register_fragment_services(
    fragment_dirs: Iterable[Path],
) -> list[tuple[str, ServiceTemplate]]:
    """Register every fragment dir's compose.yaml-declared service.

    ``fragment_dirs`` is the iterable of fragment-root directories
    (one level above the per-language ``python/`` / ``node/`` / ``rust/``
    sub-dirs). The caller derives them from the resolved plan.

    Idempotent: re-registering the same capability with the identical
    template is a no-op (matches :func:`forge.services.registry.register_service`'s
    contract). A conflicting registration raises ``ValueError`` from the
    registry — bubbles up so plan validation can surface it.

    Returns the list of ``(capability, template)`` pairs registered this
    pass; callers can log or surface the count.
    """
    registered: list[tuple[str, ServiceTemplate]] = []
    seen_roots: set[Path] = set()
    for root in fragment_dirs:
        if root in seen_roots:
            continue
        seen_roots.add(root)
        loaded = load_fragment_compose(root)
        if loaded is None:
            continue
        capability, template = loaded
        register_service(capability, template)
        registered.append((capability, template))
    return registered


def fragment_roots_from_plan(plan_ordered: Iterable[Any]) -> list[Path]:
    """Derive the fragment-root directory for each fragment in the plan.

    Each ``ResolvedFragment``'s implementations point at per-language
    sub-directories (``.../python``, ``.../node``, ``.../rust``); the
    fragment root is one level up from any of them. We pick the first
    implementation directory present and walk up — fragments with no
    implementations don't reach this code path.
    """
    from forge.feature_injector import _resolve_fragment_dir  # noqa: PLC0415

    roots: list[Path] = []
    seen: set[Path] = set()
    for rf in plan_ordered:
        for impl in rf.fragment.implementations.values():
            per_lang_dir = _resolve_fragment_dir(impl.fragment_dir)
            root = per_lang_dir.parent
            if root in seen:
                break
            seen.add(root)
            roots.append(root)
            break
    return roots
