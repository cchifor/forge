"""Public registration API for forge plugins.

Third-party packages declare themselves as forge plugins by exposing a
``register(api: ForgeAPI) -> None`` callable via the
``forge.plugins`` entry-point group. On startup, ``forge.plugins.load_all``
walks every discovered entry point, instantiates a ``ForgeAPI`` over the
live registries, and calls ``register`` — plugins use that facade to
add options, fragments, backends, frontends, commands, and emitters.

Example plugin ``pyproject.toml``::

    [project.entry-points."forge.plugins"]
    mycompany = "forge_plugin_mycompany:register"

And the plugin module::

    from forge.api import ForgeAPI
    from forge.options import Option, OptionType, FeatureCategory

    def register(api: ForgeAPI) -> None:
        api.add_option(
            Option(
                path="mycompany.audit_log",
                type=OptionType.BOOL,
                category=FeatureCategory.OBSERVABILITY,
                default=False,
                summary="Enable my company's audit log",
                enables={True: ("audit_log_mycompany",)},
            )
        )

The trust model: plugins are pip packages. Installing one grants it
full Python execution rights at forge startup. Register-only during load
— no fragment application at plugin import time. See ``docs/plugin-development.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from forge.config import BackendSpec
    from forge.fragments import Fragment
    from forge.options import Option


@dataclass
class PluginRegistration:
    """Record of a single loaded plugin for introspection by `forge --plugins list`."""

    name: str
    module: str
    version: str | None = None
    options_added: int = 0
    fragments_added: int = 0
    backends_added: int = 0
    commands_added: int = 0
    emitters_added: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "module": self.module,
            "version": self.version,
            "options_added": self.options_added,
            "fragments_added": self.fragments_added,
            "backends_added": self.backends_added,
            "commands_added": self.commands_added,
            "emitters_added": self.emitters_added,
        }


class ForgeAPI:
    """Facade handed to plugin ``register()`` callables.

    The real registries (``OPTION_REGISTRY``, ``FRAGMENT_REGISTRY``,
    ``BACKEND_REGISTRY``) live in their respective modules. ``ForgeAPI``
    is the narrow, stable surface plugins use — additions only; never
    mutate or remove.
    """

    def __init__(self, registration: PluginRegistration) -> None:
        self._registration = registration
        # Commands registered via ``add_command`` are kept in a local list
        # and folded into the CLI at dispatch time (Phase 0.3 ships the
        # hook but defers command discovery to Phase 2 when the CLI
        # command-object pattern matures).
        self._commands: list[Callable[..., Any]] = []
        # Emitters likewise — Phase 1.3 wires these.
        self._emitters: dict[str, Callable[..., Any]] = {}

    # -- Option registration ------------------------------------------------

    def add_option(self, option: "Option") -> None:
        """Register a new Option in OPTION_REGISTRY.

        The plugin is responsible for ensuring the dotted path doesn't
        collide with built-in options. On collision, the built-in wins
        and the plugin's option is rejected with a clear error.
        """
        from forge.options import OPTION_REGISTRY  # noqa: PLC0415

        if option.path in OPTION_REGISTRY:
            raise ValueError(
                f"Plugin '{self._registration.name}' tried to register option "
                f"'{option.path}', but that path is already registered. "
                "Plugin options must use a namespaced prefix (e.g. 'mycompany.audit_log')."
            )
        OPTION_REGISTRY[option.path] = option
        self._registration.options_added += 1

    # -- Fragment registration ---------------------------------------------

    def add_fragment(self, fragment: "Fragment") -> None:
        """Register a new Fragment in FRAGMENT_REGISTRY."""
        from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415

        if fragment.name in FRAGMENT_REGISTRY:
            raise ValueError(
                f"Plugin '{self._registration.name}' tried to register fragment "
                f"'{fragment.name}', but that name is already registered."
            )
        FRAGMENT_REGISTRY[fragment.name] = fragment
        self._registration.fragments_added += 1

    # -- Backend registration ----------------------------------------------

    def add_backend(self, language_value: str, spec: "BackendSpec") -> None:
        """Register a new backend language in BACKEND_REGISTRY.

        1.0.0a2+ lets plugins extend ``BackendLanguage`` via a sentinel
        (``_PluginLanguage``) so a plugin can ship a brand-new backend
        (e.g. ``go``, ``java``) without forking forge. The sentinel is
        accepted by ``BackendLanguage(value)`` via the ``_missing_``
        hook, so every downstream call that looks up a backend by its
        string value works transparently.

        Raises ``ValueError`` if ``language_value`` is already a built-in
        or already registered by another plugin.
        """
        from forge.config import (  # noqa: PLC0415
            BACKEND_REGISTRY,
            BackendLanguage,
            PLUGIN_LANGUAGES,
            register_backend_language,
        )

        # Check built-in first (enum members have fixed _value2member_map_).
        builtin: BackendLanguage | None = None
        for member in BackendLanguage:
            if member.value == language_value:
                builtin = member
                break

        if builtin is not None and builtin in BACKEND_REGISTRY:
            raise ValueError(
                f"Plugin '{self._registration.name}' tried to register backend "
                f"'{language_value}', but that language is already registered."
            )

        if builtin is not None:
            BACKEND_REGISTRY[builtin] = spec
        else:
            if language_value in PLUGIN_LANGUAGES:
                sentinel = PLUGIN_LANGUAGES[language_value]
                if sentinel in BACKEND_REGISTRY:
                    raise ValueError(
                        f"Plugin '{self._registration.name}' tried to register backend "
                        f"'{language_value}', but a plugin already claimed that name."
                    )
            sentinel = register_backend_language(language_value)
            BACKEND_REGISTRY[sentinel] = spec
        self._registration.backends_added += 1

    # -- Command registration (hook for Phase 2) ---------------------------

    def add_command(self, name: str, handler: Callable[..., Any]) -> None:
        """Register a new CLI subcommand. Handler signature: ``(args) -> int``.

        In 1.0.0a1 the hook records the command for ``forge --plugins list``
        introspection; wiring it into the argparse dispatcher lands with
        the Phase 2 command-object polish.
        """
        self._commands.append(handler)
        self._registration.commands_added += 1

    # -- Emitter registration (hook for Phase 1) ---------------------------

    def add_emitter(self, target: str, emitter: Callable[..., Any]) -> None:
        """Register a code emitter for a target language or protocol.

        Targets are free-form strings that the Phase 1 schema-first
        pipeline will consume (``python``, ``typescript``, ``dart``,
        ``openapi``). 1.0.0a1 ships the hook; the pipeline lands in 1.0.0a2.
        """
        self._emitters[target] = emitter
        self._registration.emitters_added += 1
