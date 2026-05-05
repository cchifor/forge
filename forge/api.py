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

Stable Public API
-----------------

The names listed in ``__all__`` below are the **stable plugin API**.
Plugin authors target this surface; forge releases follow SemVer with
respect to it. The CI gate at ``.github/workflows/plugin-e2e.yml``
exercises ``examples/forge-plugin-example/`` against every PR so any
breaking change to this surface surfaces before release.

+--------------------------------+--------------+-------------------+
| Name                           | Since        | Compatibility     |
+================================+==============+===================+
| ``ForgeAPI``                   | 1.0.0a1      | stable            |
| ``ForgeAPI.add_option``        | 1.0.0a1      | stable            |
| ``ForgeAPI.add_fragment``      | 1.0.0a1      | stable            |
| ``ForgeAPI.add_backend``       | 1.0.0a2      | stable            |
| ``ForgeAPI.add_frontend``      | 1.0.0a4      | stable            |
| ``ForgeAPI.add_command``       | 1.0.0a4      | stable            |
| ``ForgeAPI.add_service``       | 1.1.0-alpha.1| stable            |
| ``ForgeAPI.add_emitter``       | 1.0.0a1      | provisional       |
| ``PluginRegistration``         | 1.0.0a1      | stable            |
+--------------------------------+--------------+-------------------+

``provisional`` means the shape may still change in a 1.x minor — the
emitter pipeline isn't yet wired into a stable contract. Everything
else is stable: a breaking signature change requires a major bump.

SDK versioning
--------------

:data:`SDK_VERSION` records the version of *the public plugin API
surface itself*, distinct from the forge package version. A plugin
declares compatibility via ``api.require_sdk(">=1.1")`` in its
``register()`` callable; an incompatible host raises
:class:`PluginError` immediately so the failure is visible at plugin
load instead of as a confusing AttributeError later. Bumps to
:data:`SDK_VERSION` are tracked in ``docs/SDK_CHANGELOG.md`` — every
PR that mutates ``__all__`` of this module must add an entry there.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from forge.errors import PLUGIN_COLLISION, PLUGIN_SDK_INCOMPATIBLE, PluginError

if TYPE_CHECKING:
    from forge.config import BackendSpec, FrontendSpec
    from forge.fragments import Fragment
    from forge.options import Option


# Plugin SDK version. This is the version of the *API surface* — the
# names + signatures listed in ``__all__`` below — not the forge
# package version. Plugins declare compatibility with
# ``api.require_sdk(">=X.Y")``; bumps require a CHANGELOG entry in
# ``docs/SDK_CHANGELOG.md``.
SDK_VERSION = "1.1"


_SDK_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")


def _parse_sdk_version(version: str) -> tuple[int, int]:
    """Parse a "MAJOR.MINOR" SDK version string. Plugins target the SDK,
    not the forge package, so the format is intentionally minimal — no
    patch component, no pre-release labels."""
    m = _SDK_VERSION_RE.match(version.strip())
    if m is None:
        raise ValueError(f"SDK version {version!r} must be in 'MAJOR.MINOR' form (e.g. '1.1')")
    return int(m.group(1)), int(m.group(2))


_REQ_RE = re.compile(r"\s*([<>]=?|==)\s*(\d+\.\d+)\s*")


def _check_sdk_requirement(spec: str) -> bool:
    """Return True iff the current :data:`SDK_VERSION` satisfies ``spec``.

    ``spec`` is a comma-separated list of ``OP MAJOR.MINOR`` clauses.
    Supported operators: ``>=``, ``>``, ``<=``, ``<``, ``==``. Each
    clause is evaluated against the current SDK version; all clauses
    must match for the requirement to be satisfied. Examples::

        ">=1.1"
        ">=1.1, <2.0"
        ">=1.0, <1.2"
    """
    current = _parse_sdk_version(SDK_VERSION)
    for clause in spec.split(","):
        m = _REQ_RE.fullmatch(clause)
        if m is None:
            raise ValueError(
                f"bad SDK requirement clause {clause!r} in {spec!r}; "
                "expected '>= 1.1' / '< 2.0' / '== 1.1' shape"
            )
        op, version_str = m.group(1), m.group(2)
        target = _parse_sdk_version(version_str)
        if op == ">=" and not (current >= target):
            return False
        if op == ">" and not (current > target):
            return False
        if op == "<=" and not (current <= target):
            return False
        if op == "<" and not (current < target):
            return False
        if op == "==" and current != target:
            return False
    return True


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

    # -- SDK version negotiation -------------------------------------------

    def require_sdk(self, spec: str) -> None:
        """Assert the host forge SDK satisfies ``spec``.

        Plugin authors call this at the top of ``register()`` to fail
        fast on incompatible hosts instead of crashing with a confusing
        AttributeError when the plugin reaches for a method the host
        doesn't ship. ``spec`` is a comma-separated list of clauses
        (``">=1.1"``, ``">=1.1, <2.0"``); see :data:`SDK_VERSION`.

        Raises :class:`PluginError` (code ``PLUGIN_SDK_INCOMPATIBLE``)
        when the current SDK version is outside the requested range.
        """
        try:
            satisfied = _check_sdk_requirement(spec)
        except ValueError as exc:
            raise PluginError(
                f"Plugin {self._registration.name!r} passed an invalid "
                f"SDK requirement {spec!r}: {exc}",
                code=PLUGIN_SDK_INCOMPATIBLE,
                context={
                    "plugin": self._registration.name,
                    "requirement": spec,
                    "sdk_version": SDK_VERSION,
                },
            ) from exc
        if not satisfied:
            raise PluginError(
                f"Plugin {self._registration.name!r} requires forge SDK {spec!r} "
                f"but host ships SDK {SDK_VERSION!r}.",
                code=PLUGIN_SDK_INCOMPATIBLE,
                context={
                    "plugin": self._registration.name,
                    "requirement": spec,
                    "sdk_version": SDK_VERSION,
                },
            )

    # -- Option registration ------------------------------------------------

    def add_option(self, option: Option) -> None:
        """Register a new Option in OPTION_REGISTRY.

        The plugin is responsible for ensuring the dotted path doesn't
        collide with built-in options. On collision, the built-in wins
        and the plugin's option is rejected with a clear error.
        """
        from forge.options import OPTION_REGISTRY  # noqa: PLC0415

        if option.path in OPTION_REGISTRY:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register option "
                f"'{option.path}', but that path is already registered. "
                "Plugin options must use a namespaced prefix (e.g. 'mycompany.audit_log').",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "option",
                    "value": option.path,
                },
            )
        OPTION_REGISTRY[option.path] = option
        self._registration.options_added += 1

    # -- Fragment registration ---------------------------------------------

    def add_fragment(self, fragment: Fragment) -> None:
        """Register a new Fragment in FRAGMENT_REGISTRY."""
        from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415

        if fragment.name in FRAGMENT_REGISTRY:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register fragment "
                f"'{fragment.name}', but that name is already registered.",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "fragment",
                    "value": fragment.name,
                },
            )
        FRAGMENT_REGISTRY[fragment.name] = fragment
        self._registration.fragments_added += 1

    # -- Backend registration ----------------------------------------------

    def add_backend(self, language_value: str, spec: BackendSpec) -> None:
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
            PLUGIN_LANGUAGES,
            BackendLanguage,
            register_backend_language,
        )

        # Check built-in first (enum members have fixed _value2member_map_).
        builtin: BackendLanguage | None = None
        for member in BackendLanguage:
            if member.value == language_value:
                builtin = member
                break

        if builtin is not None and builtin in BACKEND_REGISTRY:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register backend "
                f"'{language_value}', but that language is already registered.",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "backend",
                    "value": language_value,
                },
            )

        if builtin is not None:
            BACKEND_REGISTRY[builtin] = spec
        else:
            if language_value in PLUGIN_LANGUAGES:
                sentinel = PLUGIN_LANGUAGES[language_value]
                if sentinel in BACKEND_REGISTRY:
                    raise PluginError(
                        f"Plugin '{self._registration.name}' tried to register backend "
                        f"'{language_value}', but a plugin already claimed that name.",
                        code=PLUGIN_COLLISION,
                        context={
                            "plugin": self._registration.name,
                            "kind": "backend",
                            "value": language_value,
                        },
                    )
            sentinel = register_backend_language(language_value)
            BACKEND_REGISTRY[sentinel] = spec
        self._registration.backends_added += 1

    # -- Frontend registration (1.0.0a4+) -----------------------------------

    def add_frontend(self, value: str, spec: FrontendSpec) -> None:
        """Register a new frontend framework.

        Mirrors ``add_backend``: plugins can ship their own frontend
        templates (e.g. Solid, Qwik, Remix) without forking forge.
        The sentinel is resolvable via
        ``forge.config.resolve_frontend_framework(value)``; the
        generator's per-framework dispatch treats it as a Copier-only
        render (no template-specific hooks until a plugin SDK upgrade
        lands).
        """
        from forge.config import (  # noqa: PLC0415
            FRONTEND_SPECS,
            PLUGIN_FRAMEWORKS,
            FrontendFramework,
            register_frontend_framework,
        )

        builtin: FrontendFramework | None = None
        for member in FrontendFramework:
            if member.value == value:
                builtin = member
                break

        if builtin is not None:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register frontend "
                f"'{value}', but that framework is a built-in.",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "frontend",
                    "value": value,
                },
            )

        if value in PLUGIN_FRAMEWORKS and value in FRONTEND_SPECS:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register frontend "
                f"'{value}', but a plugin already claimed that name.",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "frontend",
                    "value": value,
                },
            )

        register_frontend_framework(value)
        FRONTEND_SPECS[value] = spec

    # -- Command registration ------------------------------------------------

    def add_command(self, name: str, handler: Callable[..., Any]) -> None:
        """Register a new CLI subcommand.

        Handler signature: ``(args: argparse.Namespace) -> int``. The
        dispatcher exposes the command as ``forge --<name>`` (hyphen-
        separated), calls the handler when the user sets that flag, and
        exits with the handler's integer return code.

        1.0.0a4+ wires this into the real argparse parser (earlier alphas
        captured the handler for ``forge --plugins list`` introspection
        only). See ``forge.plugins.COMMAND_REGISTRY``.
        """
        from forge.plugins import COMMAND_REGISTRY  # noqa: PLC0415

        if name in COMMAND_REGISTRY:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register command "
                f"'{name}', but a plugin already claimed that name.",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "command",
                    "value": name,
                },
            )
        COMMAND_REGISTRY[name] = handler
        self._commands.append(handler)
        self._registration.commands_added += 1

    # -- Service registration (P0.4 / RFC-008) ------------------------------

    def add_service(self, capability: str, template: Any) -> None:
        """Register a docker-compose service keyed by capability.

        When a fragment declaring ``capabilities=(<capability>,)`` is
        resolved into the plan, the generator emits ``template`` into
        ``docker-compose.yml`` alongside the core forge services. See
        ``forge/services/registry.py`` for the :class:`ServiceTemplate`
        dataclass.

        Typical use from a plugin::

            from forge.services import ServiceTemplate

            def register(api):
                api.add_service(
                    "my_vector_store",
                    ServiceTemplate(
                        name="my_vector_store",
                        image="my/vector-store:1.0",
                        ports=['"7777:7777"'],
                    ),
                )

        Re-registering a capability with an identical template is a
        no-op. Conflicting registration raises.
        """
        from forge.services.registry import ServiceTemplate, register_service  # noqa: PLC0415

        if not isinstance(template, ServiceTemplate):
            raise PluginError(
                f"Plugin '{self._registration.name}' passed a non-ServiceTemplate "
                f"to add_service (got {type(template).__name__}).",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "service",
                    "value": capability,
                },
            )
        try:
            register_service(capability, template)
        except ValueError as exc:
            raise PluginError(
                str(exc),
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "service",
                    "value": capability,
                },
            ) from exc

    # -- Emitter registration (hook for Phase 1) ---------------------------

    def add_emitter(self, target: str, emitter: Callable[..., Any]) -> None:
        """Register a code emitter for a target language or protocol.

        Targets are free-form strings that the Phase 1 schema-first
        pipeline will consume (``python``, ``typescript``, ``dart``,
        ``openapi``). 1.0.0a1 ships the hook; the pipeline lands in 1.0.0a2.
        """
        self._emitters[target] = emitter
        self._registration.emitters_added += 1
