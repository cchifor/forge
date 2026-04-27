"""Frontend framework registry — built-in enum + plugin sentinels + spec.

Mirrors :mod:`forge.config._backend` for the frontend side. Built-ins
are Vue, Svelte, Flutter (plus the ``NONE`` sentinel for backend-only
projects); plugins extend the registry via
:func:`~forge.api.ForgeAPI.add_frontend`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from forge.config._validators import validate_features, validate_port


class FrontendFramework(Enum):
    VUE = "vue"
    SVELTE = "svelte"
    FLUTTER = "flutter"
    NONE = "none"


@dataclass(frozen=True)
class FrontendSpec:
    """Static metadata for a plugin-defined frontend framework.

    Built-in frontends (Vue, Svelte, Flutter) are handled specially by
    the generator's per-framework code paths. This spec exists so
    plugins can register new frontends without forking; the generator
    uses the spec's ``template_dir`` to locate the Copier template.

    ``uses_subdirectory`` records whether the Copier template declares
    a ``_subdirectory:`` key in its ``copier.yml``. True (the common
    case) means the template renders **into** the destination passed to
    Copier, so the generator creates ``apps/<frontend_slug>/`` up-front
    and points Copier at it. False means the template itself owns the
    directory name (Flutter's ``{{project_slug}}/`` layer), so the
    generator points Copier at ``apps/`` and lets the template create
    the inner directory. Defaults to True because that's the Copier
    default and the majority of plugin templates follow it.
    """

    template_dir: str  # path under forge/templates/, e.g. "apps/solid-frontend-template"
    display_label: str  # shown in CLI prompts and log messages
    uses_subdirectory: bool = True


def frontend_uses_subdirectory(
    framework: FrontendFramework | _PluginFramework,
) -> bool:
    """Return whether ``framework``'s template uses Copier's _subdirectory.

    Built-ins: Vue and Svelte declare ``_subdirectory:`` so render into
    their destination; Flutter's template does not and owns its inner
    directory. Plugin frameworks consult :data:`FRONTEND_SPECS`; an
    unregistered plugin framework defaults to True (the Copier
    convention) rather than raising, so the generator can keep the
    failure mode local to Copier if the template is genuinely broken.
    """
    if framework == FrontendFramework.FLUTTER:
        return False
    if isinstance(framework, FrontendFramework):
        return True
    spec = FRONTEND_SPECS.get(framework.value)
    if spec is None:
        return True
    return spec.uses_subdirectory


# Plugin-registered frontends. Keyed by the wire value (``"solid"``,
# ``"qwik"``), value is a ``_PluginFramework`` sentinel. Looked up
# via ``resolve_frontend_framework``.
PLUGIN_FRAMEWORKS: dict[str, _PluginFramework] = {}

# Specs for plugin frontends — not a dict-keyed-by-enum like
# ``BACKEND_REGISTRY`` because the built-in frameworks don't have
# specs (they use template mappings in ``generator.py``). Instead,
# ``FRONTEND_SPECS`` maps wire-value → FrontendSpec and is consulted
# by the generator when it encounters a plugin framework.
FRONTEND_SPECS: dict[str, FrontendSpec] = {}


class _PluginFramework:
    """Sentinel for plugin-registered FrontendFramework values."""

    __slots__ = ("value", "name")

    def __init__(self, value: str) -> None:
        self.value = value
        self.name = value.upper()

    def __repr__(self) -> str:
        return f"<FrontendFramework.{self.name} (plugin)>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _PluginFramework):
            return self.value == other.value
        if isinstance(other, FrontendFramework):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("FrontendFramework", self.value))


def register_frontend_framework(value: str) -> _PluginFramework:
    """Register a plugin frontend. Returns the sentinel member."""
    if value not in PLUGIN_FRAMEWORKS:
        PLUGIN_FRAMEWORKS[value] = _PluginFramework(value)
    return PLUGIN_FRAMEWORKS[value]


def resolve_frontend_framework(value: str) -> FrontendFramework | _PluginFramework:
    """Look up a frontend framework by wire value (built-in or plugin)."""
    for member in FrontendFramework:
        if member.value == value:
            return member
    if value in PLUGIN_FRAMEWORKS:
        return PLUGIN_FRAMEWORKS[value]
    raise ValueError(f"Unknown frontend framework: {value!r}")


# Reserved feature names for frontend templates
FRONTEND_RESERVED = frozenset(
    {
        "auth",
        "home",
        "profile",
        "settings",
        "chat",
        "core",
        "shared",
        "shell",
        "dashboard",
        "tasks",
        "app",
        "test",
        "lib",
        "routes",
        "api",
    }
)


@dataclass
class FrontendConfig:
    framework: FrontendFramework
    project_name: str
    description: str = "A frontend application"
    features: list[str] = field(default_factory=list)
    author_name: str = "Your Name"
    version: str = "0.1.0"
    package_manager: str = "npm"
    include_auth: bool = True
    include_chat: bool = False
    include_openapi: bool = False
    server_port: int = 5173
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    default_color_scheme: str = "blue"  # Vue only
    org_name: str = "com.example"  # Flutter only
    api_base_url: str = ""
    api_proxy_target: str = ""
    generate_e2e_tests: bool = True

    def effective_mode(self, options_mode: str = "generate") -> str:
        """Collapse two sources of frontend-mode truth into one value.

        Phase B2 introduced ``options["frontend.mode"]`` alongside the
        pre-existing ``FrontendFramework.NONE`` sentinel. Both indicate
        "don't generate a frontend" but via different paths. This helper
        returns ``"none"`` if either says so, ``"external"`` if the
        options layer explicitly sets it (framework value is irrelevant
        because the app is being generated — the mode just tells Vite
        where to send requests), otherwise ``"generate"``.

        ``options_mode`` is the value of ``options["frontend.mode"]``
        read from the enclosing ``ProjectConfig``; the FrontendConfig
        doesn't own the options dict so the caller passes it in.
        """
        if self.framework == FrontendFramework.NONE or options_mode == "none":
            return "none"
        if options_mode == "external":
            return "external"
        return "generate"

    def validate(self) -> None:
        if self.framework == FrontendFramework.NONE:
            # Feature toggles need a frontend to live in — silently accepting
            # them used to produce a "generated but nothing happened" project.
            conflicting = []
            if self.include_auth:
                conflicting.append("include_auth")
            if self.include_chat:
                conflicting.append("include_chat")
            if self.include_openapi:
                conflicting.append("include_openapi")
            if conflicting:
                raise ValueError(
                    f"Frontend feature flags ({', '.join(conflicting)}) require "
                    "a frontend framework. Either pick --frontend vue/svelte/flutter "
                    "or drop the --include-* flag."
                )
            return
        # Flutter's home_repository binds against the retrofit-generated api
        # client; turning OpenAPI off leaves it importing a deleted module.
        # Until Flutter ships a hand-rolled http client for this case, require
        # the flag.
        if self.framework == FrontendFramework.FLUTTER and not self.include_openapi:
            raise ValueError(
                "Flutter requires include_openapi=True "
                "(the home feature's retrofit client depends on the generated OpenAPI bindings)."
            )
        validate_port(self.server_port, "Frontend port")
        validate_features(self.features)
        for f in self.features:
            if f in FRONTEND_RESERVED:
                raise ValueError(f"Feature '{f}' is reserved in the frontend template.")
        valid_managers = {
            FrontendFramework.VUE: ("npm", "pnpm", "yarn"),
            FrontendFramework.SVELTE: ("npm", "pnpm", "bun"),
            FrontendFramework.FLUTTER: (),
        }
        allowed = valid_managers.get(self.framework, ())
        if allowed and self.package_manager not in allowed:
            raise ValueError(
                f"Package manager '{self.package_manager}' is not valid "
                f"for {self.framework.value}. Choose from: {', '.join(allowed)}"
            )
