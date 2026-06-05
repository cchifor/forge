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
| ``ForgeAPI.add_extractor``     | 1.2.0-alpha.1| provisional       |
| ``ForgeAPI.add_injector``      | 1.2          | provisional       |
| ``ForgeAPI.add_hook``          | 1.2          | provisional       |
| ``ForgeAPI.add_frontend_layout``| 1.3         | provisional       |
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
    from pathlib import Path

    from forge.capability_resolver import ResolvedPlan
    from forge.config import BackendSpec, FrontendFramework, FrontendSpec, ProjectConfig
    from forge.extractors.pipeline import ExtractorKind, ExtractorProtocol
    from forge.fragments import Fragment
    from forge.hooks import PhaseHook
    from forge.injectors._registry import Injector
    from forge.options import Option


# Plugin SDK version. This is the version of the *API surface* — the
# names + signatures listed in ``__all__`` below — not the forge
# package version. Plugins declare compatibility with
# ``api.require_sdk(">=X.Y")``; bumps require a CHANGELOG entry in
# ``docs/SDK_CHANGELOG.md``.
#
# 1.2 (Pillar A) — additive: two new ForgeAPI methods —
#   * ``ForgeAPI.add_injector`` (Pillar A.1) for the pluggable per-suffix
#     ApplierRegistry at :mod:`forge.injectors._registry`; lets polyglot
#     backend plugins register new file-type injectors (``.go``,
#     ``.kt``, ``.rs``) without forking ``_dispatch_injector``.
#   * ``ForgeAPI.add_hook`` (Pillar A.3) for the
#     :class:`forge.hooks.PhaseHook` protocol; lets plugins observe
#     generator phases (telemetry, SBOM, post-generate scripts) without
#     forking ``generator.py``.
SDK_VERSION = "1.3"


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


@dataclass(frozen=True)
class PluginExtractorRegistration:
    """A single ``ForgeAPI.add_extractor`` call, with the extractor kept.

    The harvester's :func:`forge.sync.project_to_forge.harvester._orchestrator._make_pipeline`
    iterates these on every harvest run and composes them with the
    built-in extractor pipeline. ``fragment=None`` is a **global
    override**: it replaces the built-in extractor for the matching
    ``kind`` for every fragment that harvest visits.

    Fragment-scoped overrides (``fragment="some_name"``) are accepted
    by :meth:`ForgeAPI.add_extractor` and retained here, but the
    harvester pipeline assembler does NOT consume them yet — that path
    requires per-fragment pipeline construction (the current
    ``_make_pipeline(selected_kinds)`` signature has no fragment slot).
    The registration is preserved so the contract surface is honest
    once that plumbing lands; until then a fragment-scoped registration
    is a no-op at harvest time.
    """

    kind: "ExtractorKind"  # noqa: UP037 — forward reference lives in extractors.pipeline
    fragment: str | None
    extractor: "ExtractorProtocol"  # noqa: UP037 — forward reference

    @property
    def as_legacy_pair(self) -> tuple[str, str | None]:
        """Back-compat shim — the older ``extractors_added`` tuple form."""
        return (self.kind, self.fragment)


@dataclass(frozen=True)
class PluginOptionRegistration:
    """A single ``ForgeAPI.add_option`` call, with the Option kept.

    Initiative #2 sub-task 1: registering an option used to drop the
    :class:`Option` object on the floor (only the ``options_added``
    integer counter survived on :class:`PluginRegistration`). Retaining
    the Option here lets downstream consumers — JSON-Schema emitters,
    plugin introspection tooling, future per-plugin validation — walk
    plugin-registered options without re-reading ``OPTION_REGISTRY``
    and guessing at provenance.

    ``plugin_name`` mirrors the harvester pattern from
    :class:`PluginExtractorRegistration`'s sibling: the registering
    plugin's name is captured so collision warnings and
    ``forge --plugins list`` can attribute each option to its owner.
    """

    option: "Option"  # noqa: UP037 — forward reference lives in forge.options
    plugin_name: str


@dataclass(frozen=True)
class PluginEmitterRegistration:
    """A single ``ForgeAPI.add_emitter`` call, with the callable kept.

    Initiative #2 sub-task 2: emitters registered via
    :meth:`ForgeAPI.add_emitter` used to live only on the ForgeAPI
    instance (``self._emitters[target]``) which the codegen pipeline
    never read. Retaining the callable on :class:`PluginRegistration`
    lets :func:`forge.codegen.pipeline.run_codegen` walk
    :data:`forge.plugins.LOADED_PLUGINS` after the built-in passes and
    invoke each registered emitter.

    The emitter callable contract is
    ``emitter(project_root: Path, config: ProjectConfig,
    resolved: ResolvedPlan | None) -> None``. ``resolved`` is the
    capability-resolver output (fragments, capabilities, option values);
    it is currently ``None`` when ``run_codegen`` is invoked from the
    legacy generator path that has not yet been plumbed with the
    resolved plan. Plugins MUST tolerate ``None``.

    Last-loaded wins on target collision (two plugins registering the
    same ``target`` string); the pipeline emits a structured warning
    naming both plugins so operators see the override happening.
    """

    target: str
    emitter: "Callable[[Path, ProjectConfig, ResolvedPlan | None], None]"  # noqa: UP037 — forward references
    plugin_name: str


@dataclass
class PluginRegistration:
    """Record of a single loaded plugin for introspection by `forge --plugins list`.

    ``extractors_added`` is the legacy ``(kind, fragment)`` tuple form
    kept for back-compat (still surfaced through :meth:`as_dict`).
    ``extractor_registrations`` is the typed-port companion landed in
    Initiative #1 sub-task 4 — it retains the extractor callable itself
    so the harvester pipeline can actually invoke plugin overrides
    instead of just observing that one was registered.

    ``option_registrations`` (Initiative #2 sub-task 1) retains the
    :class:`Option` instance for every ``ForgeAPI.add_option`` call,
    mirroring the extractor pattern. ``options_added`` is preserved as
    a legacy integer counter so ``forge --plugins list --json`` output
    stays byte-stable.

    ``emitter_registrations`` (Initiative #2 sub-task 2) retains the
    emitter callable for every ``ForgeAPI.add_emitter`` call; the
    codegen pipeline walks these after the built-in passes.
    ``emitters_added`` is preserved as a legacy integer counter for
    the same back-compat reason.
    """

    name: str
    module: str
    version: str | None = None
    options_added: int = 0
    fragments_added: int = 0
    backends_added: int = 0
    commands_added: int = 0
    emitters_added: int = 0
    extractors_added: tuple[tuple[str, str | None], ...] = ()
    extractor_registrations: tuple[PluginExtractorRegistration, ...] = ()
    option_registrations: tuple[PluginOptionRegistration, ...] = ()
    emitter_registrations: tuple[PluginEmitterRegistration, ...] = ()

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
            "extractors_added": [list(pair) for pair in self.extractors_added],
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

        Initiative #2 sub-task 1: delegates to
        :func:`forge.options.register_option` so the
        ``OPTION_ALIAS_INDEX`` is updated alongside ``OPTION_REGISTRY``
        and alias-collision checks fire just like they do for built-in
        registrations. ``register_option`` raises ``ValueError`` on
        any collision (path-vs-path, path-vs-alias, alias-vs-path,
        alias-vs-alias); we wrap that to a :class:`PluginError` with
        code :data:`forge.errors.PLUGIN_COLLISION` so the surface
        plugins see is unchanged.

        Retains the Option on
        :attr:`PluginRegistration.option_registrations` so downstream
        consumers can introspect plugin-registered options without
        guessing at provenance from ``OPTION_REGISTRY`` alone.
        """
        from forge.options import register_option  # noqa: PLC0415

        try:
            register_option(option)
        except ValueError as exc:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register option "
                f"'{option.path}', but registration failed: {exc}. "
                "Plugin options must use a namespaced prefix "
                "(e.g. 'mycompany.audit_log').",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "option",
                    "value": option.path,
                },
            ) from exc
        self._registration.option_registrations = self._registration.option_registrations + (
            PluginOptionRegistration(option=option, plugin_name=self._registration.name),
        )
        # Legacy integer counter — kept so as_dict() output is byte-stable
        # for ``forge --plugins list --json`` consumers.
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

    def add_frontend_layout(
        self,
        framework: str | FrontendFramework,
        name: str,
        template_dir: str,
        display_label: str,
        *,
        base_template_dir: str = "",
        supported: bool = True,
    ) -> None:
        """Register a selectable UI app-shell layout (``--layout``) for a frontend.

        ``framework`` may be a built-in :class:`~forge.config.FrontendFramework`
        (or its string value) or a plugin frontend previously registered via
        :meth:`add_frontend`. ``template_dir`` is the layout's Copier template
        — relative to ``forge/templates`` for templates shipped alongside the
        built-ins, or an absolute path for plugin-shipped ones (the generator
        joins it under the templates root; an absolute path wins the join).
        When ``base_template_dir`` is set, the generator renders that shared
        base first and overlays this template (two-stage render); empty means
        a self-contained single render.

        Additive since SDK 1.3.
        """
        from forge.config import (  # noqa: PLC0415
            FrontendFramework,
            resolve_frontend_framework,
        )
        from forge.layout_variants import (  # noqa: PLC0415
            LayoutVariant,
            register_layout_variant,
        )

        fw = (
            framework
            if isinstance(framework, FrontendFramework)
            else resolve_frontend_framework(framework)
        )
        register_layout_variant(
            LayoutVariant(
                framework=fw,
                name=name,
                template_dir=template_dir,
                display_label=display_label,
                supported=supported,
                base_template_dir=base_template_dir,
            )
        )

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

    # -- Emitter registration -----------------------------------------------

    def add_emitter(self, target: str, emitter: Callable[..., Any]) -> None:
        """Register a code emitter for a target language or protocol.

        Targets are free-form strings that the codegen pipeline picks
        up after its built-in passes run (``python``, ``typescript``,
        ``dart``, ``openapi``, or any plugin-defined string).

        The emitter callable contract is::

            emitter(project_root: Path,
                    config: ProjectConfig,
                    resolved: ResolvedPlan | None) -> None

        where ``project_root`` is the just-generated project tree,
        ``config`` is the resolved :class:`ProjectConfig`, and
        ``resolved`` is the capability-resolver output. ``resolved``
        is ``None`` when ``run_codegen`` is invoked from the legacy
        generator path that hasn't been plumbed with the plan yet;
        plugin emitters MUST tolerate that.

        Initiative #2 sub-task 2 retains the callable on
        :attr:`PluginRegistration.emitter_registrations` so
        :func:`forge.codegen.pipeline.run_codegen` can walk
        :data:`forge.plugins.LOADED_PLUGINS` and invoke each
        registered emitter after the built-in passes. Last-loaded
        wins on target collision; the pipeline emits a structured
        warning naming both plugins. ``self._emitters[target]`` is
        kept for back-compat with the original 1.0.0a1 API surface
        (and is overwritten on collision by the same last-wins rule).
        ``emitters_added`` is preserved as a legacy integer counter
        for byte-stable ``forge --plugins list --json`` output.
        """
        self._emitters[target] = emitter
        self._registration.emitter_registrations = self._registration.emitter_registrations + (
            PluginEmitterRegistration(
                target=target,
                emitter=emitter,
                plugin_name=self._registration.name,
            ),
        )
        self._registration.emitters_added += 1

    # -- Extractor registration (hook for Phase 4 forge --harvest) ----------

    def add_extractor(
        self,
        kind: ExtractorKind,
        extractor: ExtractorProtocol,
        *,
        fragment: str | None = None,
    ) -> None:
        """Register a custom extractor for a kind, optionally fragment-scoped.

        Plugins that ship custom appliers should ship paired extractors
        so their fragments survive round-trip (``forge --harvest``).
        The built-in pipeline ships extractors for kind ``"files"`` /
        ``"block"`` / ``"deps"`` / ``"env"`` — register one of those
        values to swap the default for the matching kind.

        ``fragment=None`` (default) is a **global override**: the
        plugin's extractor replaces the built-in for every fragment
        the harvester visits. Initiative #1 sub-task 4 wired this
        path end-to-end.

        ``fragment="some_name"`` is **accepted and retained but NOT
        yet invoked** by the harvester — fragment-scoped overrides
        need per-fragment pipeline construction that the current
        :func:`forge.sync.project_to_forge.harvester._orchestrator._make_pipeline`
        signature does not support. The registration is preserved on
        :attr:`PluginRegistration.extractor_registrations` so the SDK
        contract is honest; the harvester emits a one-shot warning
        the first time it skips one in a process.

        ``extractor`` must satisfy
        :class:`forge.extractors.pipeline.ExtractorProtocol`. The
        legacy :attr:`extractors_added` tuple form is still populated
        for back-compat with ``forge --plugins list --json`` consumers.

        Raises :class:`PluginError` when ``kind`` is not a valid
        :data:`ExtractorKind`. Plugins that need a new extraction kind
        should bump the SDK rather than smuggling a string through here.
        """
        from forge.errors import PluginError  # noqa: PLC0415
        from forge.extractors.pipeline import EXTRACTOR_KINDS  # noqa: PLC0415

        if kind not in EXTRACTOR_KINDS:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register an "
                f"extractor for unknown kind {kind!r}. Valid kinds: "
                f"{sorted(EXTRACTOR_KINDS)}.",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "extractor",
                    "value": str(kind),
                },
            )
        registration = PluginExtractorRegistration(
            kind=kind, fragment=fragment, extractor=extractor
        )
        self._registration.extractor_registrations = self._registration.extractor_registrations + (
            registration,
        )
        # Legacy tuple — kept so as_dict() output is byte-stable for
        # existing JSON consumers (``forge --plugins list --json``).
        # Delegates to the dataclass's own legacy-pair shim so the two
        # representations can't drift if the field shape changes.
        self._registration.extractors_added = self._registration.extractors_added + (
            registration.as_legacy_pair,
        )

    # -- Injector registration (Pillar A.1, SDK 1.2) ------------------------

    def add_injector(self, suffix: str, injector: Injector) -> None:
        """Register a per-suffix injector with the ApplierRegistry.

        Pillar A.1 replaced the hardcoded ``if/elif`` chain in
        :func:`forge.appliers.injection._dispatch_injector` with a
        pluggable registry at :mod:`forge.injectors._registry`. Plugins
        ship language-specific injectors via this hook so a Go-backend
        plugin can wire a ``.go`` AST injector — or a Kotlin plugin a
        ``.kt`` injector — without forking forge.

        ``suffix`` is a lowercase file extension including the leading
        dot (``".go"``, ``".kt"``, ``".rs"``) or the wildcard literal
        ``"*"`` to override the catch-all sentinel-based text fallback.
        Suffix matching is case-insensitive at lookup time.

        ``injector`` is any callable satisfying the
        :class:`forge.injectors._registry.Injector` protocol — i.e. a
        positional signature of
        ``(file: Path, feature_key: str, marker: str,
        snippet: str, position: str) -> None``. The injector mutates
        the file at ``file`` in place; it inherits the same
        replace-in-place idempotency contract every built-in
        injector follows (re-applying with the same tag replaces the
        existing sentinel block rather than duplicating).

        Last-write wins on collision: re-registering ``".py"`` silently
        replaces the built-in LibCST injector. The contract is
        intentional — plugins that wrap a built-in (e.g. add tracing)
        register their wrapped version directly.

        Raises :class:`PluginError` (code
        :data:`forge.errors.PLUGIN_COLLISION`) if ``suffix`` is empty,
        missing its leading dot, or contains characters that can't
        appear in a real file suffix. The underlying
        :func:`register_injector` ``ValueError`` is wrapped so the
        plugin surface stays plugin-coded.

        Provisional in 1.2: the injector callable contract may grow a
        return value (e.g. a structured diff for telemetry) in a later
        minor. The positional signature won't change without a major
        bump.
        """
        from forge.injectors._registry import register_injector  # noqa: PLC0415

        try:
            register_injector(suffix, injector)
        except ValueError as exc:
            raise PluginError(
                f"Plugin '{self._registration.name}' tried to register an "
                f"injector for suffix {suffix!r}, but registration failed: {exc}.",
                code=PLUGIN_COLLISION,
                context={
                    "plugin": self._registration.name,
                    "kind": "injector",
                    "value": suffix,
                },
            ) from exc

    # -- Phase-hook registration (Pillar A.3, SDK 1.2) ----------------------

    def add_hook(self, hook: PhaseHook) -> None:
        """Register a :class:`forge.hooks.PhaseHook` to observe generation.

        Hooks fire from the existing :func:`forge.logging.phase_timer`
        context that wraps every generator phase: ``on_phase_start`` /
        ``on_phase_end`` for each ``with phase_timer(...)`` block,
        ``on_generate_complete`` once at the end of
        :func:`forge.generator.generate` with the populated
        :class:`forge.reports.GenerationReport` (or ``None`` when the
        caller didn't request the richer payload).

        Plugin authors typically pass an instance::

            from forge.hooks import PhaseHook
            from forge.api import ForgeAPI

            class TelemetryHook:
                def on_phase_start(self, name, ctx): ...
                def on_phase_end(self, name, ctx, duration_ms, error): ...
                def on_generate_complete(self, report): ...

            def register(api: ForgeAPI) -> None:
                api.require_sdk(">=1.2")
                api.add_hook(TelemetryHook())

        Hook exceptions are swallowed + logged inside the fire helpers
        — the contract is "buggy plugin doesn't crash generation".
        Hooks fire in registration order (FIFO across all plugins).

        Provisional in 1.2: the protocol is additive, so adding methods
        in a later minor is non-breaking, but the ``ctx`` dict's keys
        are not yet a stable schema — they reflect whatever the
        generator passed to ``phase_timer(..., **ctx)`` at the call
        site. Treat as observability surface, not control surface.
        """
        from forge.hooks import register_hook  # noqa: PLC0415

        register_hook(hook)


# The stable plugin API surface. The module docstring's "Stable Public API"
# table is the human-facing contract; this tuple is the machine-readable one.
# ``ForgeAPI`` exposes the add_* registration methods (stable + provisional
# per the table); the Plugin*Registration dataclasses are the introspection
# records ``forge --plugins list`` reads; ``SDK_VERSION`` is the negotiated
# plugin-SDK version. Mutating this tuple requires a docs/SDK_CHANGELOG.md
# entry (see the module docstring) — adding a name is additive, removing one
# is a major bump.
__all__ = (
    "ForgeAPI",
    "PluginRegistration",
    "PluginExtractorRegistration",
    "PluginOptionRegistration",
    "PluginEmitterRegistration",
    "SDK_VERSION",
)
