"""Entry-point discovery and loading for forge plugins.

Plugins register themselves via the ``forge.plugins`` entry-point group.
At startup (``forge.cli.main:main`` before parser construction),
``load_all()`` walks every discovered entry point, instantiates a
``ForgeAPI`` handle for each, and calls the plugin's ``register``
callable.

The loaded-plugin roster is captured in ``LOADED_PLUGINS`` (module-level)
so ``forge --plugins list`` can enumerate them after load.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import metadata
from typing import TYPE_CHECKING, Any

from forge.api import ForgeAPI, PluginRegistration
from forge.errors import FragmentError
from forge.fragments import FRAGMENT_REGISTRY

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "forge.plugins"

# Populated by ``load_all``. Each entry describes a plugin that was
# successfully discovered and registered. ``forge --plugins list``
# introspects this list after load.
LOADED_PLUGINS: list[PluginRegistration] = []

# Plugins that failed to load. Reported by ``forge --plugins list``
# alongside LOADED_PLUGINS so discovery bugs are visible.
FAILED_PLUGINS: list[tuple[str, str]] = []

# Plugin-registered CLI commands. Keyed by the flag name (hyphen-separated
# string the user types as ``forge --<name>``); value is the handler
# ``(args: argparse.Namespace) -> int``. Populated by
# ``ForgeAPI.add_command``; consumed by ``forge.cli.parser._build_parser``
# to inject plugin flags and by ``forge.cli.main`` to dispatch them.
COMMAND_REGISTRY: dict[str, Callable[..., Any]] = {}


def load_all() -> list[PluginRegistration]:
    """Discover and load every plugin registered under ``forge.plugins``.

    Idempotent — if called twice, the second call is a no-op. Errors in
    one plugin's ``register`` don't block other plugins from loading;
    the failure is captured in ``FAILED_PLUGINS`` with the exception
    message for diagnostic display.

    Returns the updated ``LOADED_PLUGINS`` list for convenience.
    """
    if LOADED_PLUGINS or FAILED_PLUGINS:
        # Already loaded this process.
        return LOADED_PLUGINS

    for ep in _iter_entry_points():
        registration = PluginRegistration(
            name=ep.name,
            module=getattr(ep, "value", None) or getattr(ep, "module", "<unknown>"),
            version=_plugin_version(ep),
        )
        try:
            register_fn = ep.load()
        except Exception as exc:  # noqa: BLE001 — surface the class+message
            FAILED_PLUGINS.append((ep.name, f"load failed: {type(exc).__name__}: {exc}"))
            logger.warning("forge plugin %r failed to load: %s", ep.name, exc)
            continue

        if not callable(register_fn):
            FAILED_PLUGINS.append(
                (ep.name, f"entry point target is not callable (got {type(register_fn).__name__})")
            )
            continue

        api = ForgeAPI(registration)
        try:
            register_fn(api)
        except Exception as exc:  # noqa: BLE001
            FAILED_PLUGINS.append((ep.name, f"register failed: {type(exc).__name__}: {exc}"))
            logger.warning("forge plugin %r register() raised: %s", ep.name, exc)
            continue

        LOADED_PLUGINS.append(registration)
        from forge.logging import get_logger, log_event  # noqa: PLC0415

        log_event(
            get_logger("plugins"),
            "plugin.loaded",
            plugin=registration.name,
            version=registration.version,
            options_added=registration.options_added,
            fragments_added=registration.fragments_added,
            backends_added=registration.backends_added,
            commands_added=registration.commands_added,
        )

    # Epic I (1.1.0-alpha.1) — lock the fragment registry after every
    # plugin has had its turn to register. A broken plugin graph (orphan
    # depends_on, cycle) surfaces here with a clear error rather than
    # deep inside generation. Late registration — e.g. a plugin that
    # tries to add a fragment during a CLI verb rather than at load —
    # now hits `PluginError(PLUGIN_REGISTRY_FROZEN)`.
    try:
        FRAGMENT_REGISTRY.freeze()
    except FragmentError as exc:
        # The registry is in an internally-inconsistent state because
        # something in the built-in + plugin union is broken. Record
        # it as a plugin-load failure rather than crashing — forge should
        # still be able to run introspection verbs (`--list`, `--plugins`)
        # so the operator can diagnose.
        FAILED_PLUGINS.append(("<registry audit>", f"{type(exc).__name__}: {exc}"))
        logger.error("FRAGMENT_REGISTRY audit failed: %s", exc)

    return LOADED_PLUGINS


def _iter_entry_points() -> Iterable[metadata.EntryPoint]:
    """Return entry points in the ``forge.plugins`` group.

    Python 3.10+ supports ``entry_points().select(group=...)``. Older
    selectors return a dict keyed by group. Handle both shapes.
    """
    eps = metadata.entry_points()
    if hasattr(eps, "select"):
        return eps.select(group=ENTRY_POINT_GROUP)
    # Dict-shaped result (EntryPoints before 3.10)
    return eps.get(ENTRY_POINT_GROUP, ())  # type: ignore[attr-defined]


def _plugin_version(ep: metadata.EntryPoint) -> str | None:
    """Best-effort version discovery for a plugin entry point.

    Extracts the distribution name from ``ep.dist`` when present, else
    returns None. ``ep.dist`` is populated by modern importlib.metadata
    but missing on Python 3.8 back-compat shims.
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    version = getattr(dist, "version", None)
    return str(version) if version is not None else None


def reset_for_tests() -> None:
    """Clear LOADED_PLUGINS / FAILED_PLUGINS / COMMAND_REGISTRY — use ONLY from tests.

    Also thaws ``FRAGMENT_REGISTRY`` so a subsequent ``load_all()`` call can
    register plugin fragments + re-freeze cleanly.
    """
    LOADED_PLUGINS.clear()
    FAILED_PLUGINS.clear()
    COMMAND_REGISTRY.clear()
    FRAGMENT_REGISTRY.frozen = False
