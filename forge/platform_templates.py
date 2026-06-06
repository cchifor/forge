"""Platform presets — the selectable ``--platform`` multi-service bundles.

This is the platform-scale analogue of :mod:`forge.layout_variants` (the
frontend ``--layout`` system) and :mod:`forge.backend_app_templates` (the
backend ``app_template`` system). Where a :class:`LayoutVariant` records which
template renders one UI shell and a :class:`BackendApplicationTemplate` records
which template renders one service shape, a :class:`PlatformTemplate` records a
*whole-project shape*: a bundle of option overrides + per-backend
``app_template``/``depends_on`` assignments + an optional frontend that
together stand up a coherent platform (e.g. an N-service S2S microservices
platform behind a gateway).

**Application is a config layer, not a renderer.** A platform preset is applied
as the **lowest-priority** configuration layer — strictly below user CLI flags
and config-file values, exactly like a default. The CLI builder deep-merges the
preset's :meth:`PlatformTemplate.as_config_dict` *under* the user cfg, so any
key the user sets wins. Selecting no platform (the default) is a no-op, which is
why every golden snapshot stays byte-identical: no golden preset uses
``--platform``.

**Discovery.** Presets are auto-discovered from manifest files at
``forge/templates/platforms/<name>/platform.toml`` (mirroring the
layout/backend-variant discovery pattern). Adding a preset is a drop-in: ship a
manifest; no code change here. Plugins can also register at runtime via
:meth:`forge.api.ForgeAPI.add_platform_template`.

Manifest shape::

    [platform]
    name = "microservices"
    display_label = "Microservices platform"
    description = "N services behind a gateway, S2S auth, event bus"
    include_keycloak = true
    database_mode = "compose"          # optional override

    [platform.options]                 # merged UNDER user options (dotted keys)
    "auth.service_discovery" = true
    "infrastructure.event_bus" = "postgres_notify"

    [[platform.backends]]              # per-backend shape + wiring
    name = "gateway"
    language = "python"
    app_template = "api-gateway"
    server_port = 5010
    depends_on = ["orders", "inventory"]

    [platform.frontend]                # omit entirely for a headless platform
    framework = "vue"
    layout = "sidebar"
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Root of the platform-manifest tree (``platforms/<name>/platform.toml``).
_PLATFORMS_ROOT = Path(__file__).parent / "templates" / "platforms"


@dataclass(frozen=True)
class PlatformTemplate:
    """One selectable ``--platform`` preset.

    A preset is a *config layer*, not a template tree: it carries the option
    overrides, per-backend wiring, and optional frontend that, applied as the
    lowest-priority layer, stand up a coherent multi-service platform.

    Attributes:
        name: The preset slug (e.g. ``"microservices"``) — the ``--platform``
            value and the value persisted to ``ProjectConfig.platform_template``.
        display_label: Human-readable name for CLI / interactive listings.
        description: One-line summary of what the preset stands up.
        include_keycloak: The top-level ``include_keycloak`` the preset seeds.
            S2S synthesis (``auth.service_discovery``) requires Keycloak, so any
            preset that enables service discovery must set this ``True``.
        options: Dotted option-path → value, merged *under* the user's
            ``options`` block (preset loses to the user on any shared key).
        backends: One dict per backend the preset materializes. Each dict may
            carry ``name``, ``language``, ``app_template``, ``server_port``,
            ``depends_on`` — the keys the cfg ``backends:`` list understands.
        frontend: The cfg ``frontend:`` block (e.g.
            ``{"framework": "vue", "layout": "sidebar"}``), or ``None`` for a
            headless platform (no frontend at all).
        database_mode: Optional ``database.mode`` override (e.g. ``"none"``).
            ``None`` (default) leaves the resolver's default in place.
    """

    name: str
    display_label: str
    description: str
    include_keycloak: bool = False
    options: dict[str, Any] = field(default_factory=dict)
    backends: tuple[dict[str, Any], ...] = ()
    frontend: dict[str, Any] | None = None
    database_mode: str | None = None

    def as_config_dict(self) -> dict[str, Any]:
        """Return a builder-cfg-shaped dict for this preset.

        The result is merged *under* the user's cfg by the CLI builder, so it
        only carries the keys the preset actually sets — absent keys fall
        through to the user cfg / resolver defaults. ``backends`` is emitted as
        a fresh list of fresh dicts so callers can mutate it without touching
        the frozen preset; ``options`` is likewise copied. ``frontend`` is
        omitted entirely (not set to ``None``) for headless presets so the
        builder's ``frontend.framework`` default (``"none"``) governs.
        """
        cfg: dict[str, Any] = {
            "include_keycloak": self.include_keycloak,
            "options": dict(self.options),
            "backends": [dict(be) for be in self.backends],
        }
        if self.frontend is not None:
            cfg["frontend"] = dict(self.frontend)
        if self.database_mode is not None:
            # database.mode rides in the options block — it is an Option path,
            # not a top-level cfg key.
            cfg["options"]["database.mode"] = self.database_mode
        return cfg


PLATFORM_TEMPLATES: dict[str, PlatformTemplate] = {}


def register_platform_template(template: PlatformTemplate) -> None:
    """Register a :class:`PlatformTemplate`. Raises on a duplicate name."""
    if template.name in PLATFORM_TEMPLATES:
        raise ValueError(f"PlatformTemplate {template.name!r} is already registered")
    PLATFORM_TEMPLATES[template.name] = template


def get_platform_template(name: str) -> PlatformTemplate | None:
    """Return the preset named ``name``, or ``None`` if unknown."""
    return PLATFORM_TEMPLATES.get(name)


def available_platform_templates() -> tuple[str, ...]:
    """Return every registered preset name, sorted."""
    return tuple(sorted(PLATFORM_TEMPLATES))


def _coerce_backends(raw: Any) -> tuple[dict[str, Any], ...]:
    """Coerce a manifest's ``[[platform.backends]]`` array into dicts."""
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, dict):
            out.append({str(k): v for k, v in entry.items()})
    return tuple(out)


def _coerce_options(raw: Any) -> dict[str, Any]:
    """Coerce a manifest's ``[platform.options]`` table into a dotted dict."""
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items()}


def _coerce_frontend(raw: Any) -> dict[str, Any] | None:
    """Coerce a manifest's ``[platform.frontend]`` table, or ``None``."""
    if not isinstance(raw, dict):
        return None
    return {str(k): v for k, v in raw.items()}


def _discover() -> None:
    """Discover presets from ``platforms/<name>/platform.toml``."""
    if not _PLATFORMS_ROOT.is_dir():
        return
    for manifest in sorted(_PLATFORMS_ROOT.glob("*/platform.toml")):
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        platform = data.get("platform")
        if not isinstance(platform, dict):
            continue
        name = platform.get("name")
        if not name:
            continue
        database_mode = platform.get("database_mode")
        register_platform_template(
            PlatformTemplate(
                name=str(name),
                display_label=str(platform.get("display_label", name)),
                description=str(platform.get("description", "")),
                include_keycloak=bool(platform.get("include_keycloak", False)),
                options=_coerce_options(platform.get("options")),
                backends=_coerce_backends(platform.get("backends")),
                frontend=_coerce_frontend(platform.get("frontend")),
                database_mode=str(database_mode) if database_mode is not None else None,
            )
        )


def _reset_for_tests() -> None:
    """Clear the registry and re-discover built-ins (test isolation)."""
    PLATFORM_TEMPLATES.clear()
    _discover()


_discover()
