"""Configuration dataclasses for forge."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Keycloak realm that maps to Host(`app.localhost`) for Gatekeeper tenant extraction.
# Used as both the default user-facing realm name and the template fallback.
DEFAULT_REALM = "app"

# Traefik dashboard host port. Kept in sync with `deploy/docker-compose.yml.j2`.
TRAEFIK_DASHBOARD_PORT = 19090


def keycloak_client_id_from(project_name: str) -> str:
    """Normalize a project name into a Keycloak client ID (hyphen-separated, lowercase)."""
    return project_name.lower().replace(" ", "-").replace("_", "-")


class BackendLanguage(Enum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"


# Plugin-registered backend language values. Keyed by the wire value
# (``"go"``, ``"java"``), value is a sentinel object (_PluginLanguage)
# that mimics a BackendLanguage member well enough for the generator
# dispatch + fragment lookup. Look up via ``resolve_backend_language``.
PLUGIN_LANGUAGES: dict[str, "_PluginLanguage"] = {}


class _PluginLanguage:
    """Synthetic BackendLanguage member for plugin-registered languages.

    Behaves like a frozen enum member: has ``.value``, ``.name``, and
    hashes consistently so it works as a dict key in BACKEND_REGISTRY.
    The Python enum machinery refuses to return non-Enum values from
    ``_missing_``, so we expose a separate resolution function instead
    of pretending this is a real member.
    """

    __slots__ = ("value", "name")

    def __init__(self, value: str) -> None:
        self.value = value
        self.name = value.upper()

    def __repr__(self) -> str:
        return f"<BackendLanguage.{self.name} (plugin)>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _PluginLanguage):
            return self.value == other.value
        if isinstance(other, BackendLanguage):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("BackendLanguage", self.value))


def register_backend_language(value: str) -> "_PluginLanguage":
    """Register a plugin language value. Returns the sentinel member."""
    if value not in PLUGIN_LANGUAGES:
        PLUGIN_LANGUAGES[value] = _PluginLanguage(value)
    return PLUGIN_LANGUAGES[value]


def resolve_backend_language(value: str) -> "BackendLanguage | _PluginLanguage":
    """Look up a language by string value. Checks built-in enum first,
    then plugin-registered sentinels. Raises ValueError if neither
    matches — callers treat that as "unknown language".

    Used by fragment/generator code that deals with language strings
    from YAML configs or plugin metadata.
    """
    for member in BackendLanguage:
        if member.value == value:
            return member
    if value in PLUGIN_LANGUAGES:
        return PLUGIN_LANGUAGES[value]
    raise ValueError(f"Unknown backend language: {value!r}")


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
    """

    template_dir: str  # path under forge/templates/, e.g. "apps/solid-frontend-template"
    display_label: str  # shown in CLI prompts and log messages


# Plugin-registered frontends. Keyed by the wire value (``"solid"``,
# ``"qwik"``), value is a ``_PluginFramework`` sentinel. Looked up
# via ``resolve_frontend_framework``.
PLUGIN_FRAMEWORKS: dict[str, "_PluginFramework"] = {}

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


def register_frontend_framework(value: str) -> "_PluginFramework":
    """Register a plugin frontend. Returns the sentinel member."""
    if value not in PLUGIN_FRAMEWORKS:
        PLUGIN_FRAMEWORKS[value] = _PluginFramework(value)
    return PLUGIN_FRAMEWORKS[value]


def resolve_frontend_framework(value: str) -> "FrontendFramework | _PluginFramework":
    """Look up a frontend framework by wire value (built-in or plugin)."""
    for member in FrontendFramework:
        if member.value == value:
            return member
    if value in PLUGIN_FRAMEWORKS:
        return PLUGIN_FRAMEWORKS[value]
    raise ValueError(f"Unknown frontend framework: {value!r}")


@dataclass(frozen=True)
class BackendSpec:
    """Static metadata for a backend language: template, prompts, version field.

    Adding a 4th backend means adding one entry here plus one Copier template
    directory under `forge/templates/services/`. The CLI prompt loop, generator
    dispatch, and variable-mapper context builder all read from this registry.
    """

    template_dir: str  # path under forge/templates/, e.g. "services/python-service-template"
    display_label: str  # shown in CLI prompts and log messages
    version_field: str  # name of the BackendConfig attribute holding the version
    version_choices: tuple[str, ...]  # interactive prompt choices, first is default


# BACKEND_REGISTRY keys are either real ``BackendLanguage`` members or
# ``_PluginLanguage`` sentinels — both share the ``.value`` attribute so
# downstream code can treat them uniformly.
BACKEND_REGISTRY: dict["BackendLanguage | _PluginLanguage", BackendSpec] = {
    BackendLanguage.PYTHON: BackendSpec(
        template_dir="services/python-service-template",
        display_label="Python (FastAPI)",
        version_field="python_version",
        version_choices=("3.13", "3.12", "3.11"),
    ),
    BackendLanguage.NODE: BackendSpec(
        template_dir="services/node-service-template",
        display_label="Node.js (Fastify)",
        version_field="node_version",
        version_choices=("22", "20", "18"),
    ),
    BackendLanguage.RUST: BackendSpec(
        template_dir="services/rust-service-template",
        display_label="Rust (Axum)",
        version_field="rust_edition",
        version_choices=("2024", "2021"),
    ),
}


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


def validate_port(port: int, name: str = "Port") -> None:
    if not (1024 <= port <= 65535):
        raise ValueError(f"{name} must be between 1024 and 65535, got {port}")


def validate_features(features: list[str]) -> None:
    seen: set[str] = set()
    for f in features:
        f = f.strip()
        if not f:
            continue
        if not re.match(r"^[a-z][a-z0-9_]*$", f):
            raise ValueError(
                f"Feature '{f}' must be lowercase, start with a letter, "
                "and contain only letters, digits, and underscores."
            )
        if keyword.iskeyword(f):
            raise ValueError(f"Feature '{f}' is a Python keyword.")
        if f in seen:
            raise ValueError(f"Duplicate feature: '{f}'")
        seen.add(f)


@dataclass
class BackendConfig:
    """Backend service configuration."""

    name: str = "backend"
    project_name: str = ""
    language: BackendLanguage = BackendLanguage.PYTHON
    description: str = "A microservice"
    features: list[str] = field(default_factory=lambda: ["items"])
    python_version: str = "3.13"
    node_version: str = "22"
    rust_edition: str = "2024"
    server_port: int = 5000

    def validate(self) -> None:
        validate_port(self.server_port, f"Backend '{self.name}' port")
        if not re.match(r"^[a-z][a-z0-9_-]*$", self.name):
            raise ValueError(f"Backend name '{self.name}' must be lowercase kebab/snake case.")
        if self.features:
            validate_features(self.features)


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

    def validate(self) -> None:
        if self.framework == FrontendFramework.NONE:
            return
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


@dataclass
class ProjectConfig:
    project_name: str
    output_dir: str = "."
    backends: list[BackendConfig] = field(default_factory=list)
    frontend: FrontendConfig | None = None
    include_keycloak: bool = False
    keycloak_port: int = 18080
    # Typed configuration options. Path → value (dotted key like
    # "rag.backend" or "middleware.rate_limit"). Only paths that are
    # explicitly set appear here; defaults are applied by the resolver
    # in `capability_resolver.resolve`.
    options: dict[str, Any] = field(default_factory=dict)

    # Backward compatibility: single backend access
    @property
    def backend(self) -> BackendConfig | None:
        """Return the first backend, or None. For backward compatibility."""
        return self.backends[0] if self.backends else None

    @backend.setter
    def backend(self, value: BackendConfig | None) -> None:
        """Set a single backend. For backward compatibility."""
        if value is None:
            self.backends = []
        elif self.backends:
            self.backends[0] = value
        else:
            self.backends.append(value)

    def validate(self) -> None:
        if not self.project_name.strip():
            raise ValueError("Project name cannot be empty.")
        for bc in self.backends:
            bc.validate()
        if self.frontend:
            self.frontend.validate()
        self._validate_backend_uniqueness()
        self._validate_features_against_reserved()
        ports = self._validate_ports()
        if self.include_keycloak:
            self._validate_keycloak_ports(ports)
        self._validate_options()
        self._resolve_once()

    def _validate_options(self) -> None:
        """Check every option path is registered and each value is valid.

        Same close-match suggestion pattern the CLI uses for typos.
        Delegates shape checks (type matching, enum bounds, min/max) to
        ``Option.validate_value``.
        """
        import difflib  # noqa: PLC0415

        from forge.options import OPTION_REGISTRY  # noqa: PLC0415

        for path, value in self.options.items():
            spec = OPTION_REGISTRY.get(path)
            if spec is None:
                matches = difflib.get_close_matches(path, list(OPTION_REGISTRY), n=1, cutoff=0.5)
                hint = f" Did you mean: {matches[0]}?" if matches else ""
                raise ValueError(
                    f"Unknown option {path!r}.{hint} "
                    f"Known options: {sorted(OPTION_REGISTRY) or '(none)'}"
                )
            try:
                spec.validate_value(value)
            except ValueError as exc:
                # Surface with the same shape config-layer errors use.
                raise ValueError(str(exc)) from exc

    def _resolve_once(self) -> None:
        """Resolve options to catch bad combinations early.

        Imported inline to avoid a config → resolver → config import cycle.
        """
        from forge.capability_resolver import resolve  # noqa: PLC0415
        from forge.errors import GeneratorError  # noqa: PLC0415

        try:
            resolve(self)
        except GeneratorError as e:
            # Surface resolver errors as ValueError so cli.main's config-error
            # path handles them uniformly with the other validations above.
            raise ValueError(str(e)) from e

    def _validate_backend_uniqueness(self) -> None:
        names = [bc.name for bc in self.backends]
        if len(names) != len(set(names)):
            raise ValueError("Backend names must be unique.")

    def _validate_features_against_reserved(self) -> None:
        """Backend feature names must not collide with frontend's reserved page names."""
        if not (self.frontend and self.frontend.framework != FrontendFramework.NONE):
            return
        for bc in self.backends:
            for f in bc.features:
                if f in FRONTEND_RESERVED:
                    raise ValueError(
                        f"Feature '{f}' on backend '{bc.name}' is reserved "
                        f"in the frontend template."
                    )

    def _validate_ports(self) -> dict[int, str]:
        """Detect host-port collisions across backends, frontend, and Postgres.

        Returns the populated ports map so keycloak validation can extend it.
        """
        ports: dict[int, str] = {}
        for bc in self.backends:
            if bc.server_port in ports:
                raise ValueError(
                    f"Port {bc.server_port} is used by both '{bc.name}' "
                    f"and '{ports[bc.server_port]}'."
                )
            ports[bc.server_port] = bc.name
        if (
            self.frontend
            and self.frontend.framework != FrontendFramework.NONE
            and self.frontend.framework != FrontendFramework.FLUTTER
        ):
            p = self.frontend.server_port
            if p in ports:
                raise ValueError(f"Port {p} is used by both frontend and {ports[p]}.")
            ports[p] = "frontend"
        db_port = 5432
        if db_port in ports:
            raise ValueError(f"Port {db_port} (PostgreSQL) conflicts with {ports[db_port]}.")
        ports[db_port] = "postgres"
        return ports

    def _validate_keycloak_ports(self, ports: dict[int, str]) -> None:
        validate_port(self.keycloak_port, "Keycloak port")
        if TRAEFIK_DASHBOARD_PORT in ports:
            raise ValueError(
                f"Port {TRAEFIK_DASHBOARD_PORT} (Traefik dashboard) "
                f"conflicts with {ports[TRAEFIK_DASHBOARD_PORT]}."
            )
        ports[TRAEFIK_DASHBOARD_PORT] = "Traefik dashboard"
        if self.keycloak_port in ports:
            raise ValueError(
                f"Port {self.keycloak_port} (Keycloak) conflicts with {ports[self.keycloak_port]}."
            )
        ports[self.keycloak_port] = "Keycloak"

    @property
    def all_features(self) -> list[str]:
        """Aggregate deduplicated features across all backends, preserving order."""
        seen: set[str] = set()
        features: list[str] = []
        for bc in self.backends:
            for f in bc.features:
                if f not in seen:
                    seen.add(f)
                    features.append(f)
        return features

    @property
    def project_slug(self) -> str:
        return self.project_name.lower().replace(" ", "_").replace("-", "_")

    @property
    def backend_slug(self) -> str:
        """Directory name for the first (or only) backend. Backward compat."""
        return self.backends[0].name if self.backends else "backend"

    @property
    def frontend_slug(self) -> str:
        """Fixed directory name for the generated frontend application."""
        return "frontend"
