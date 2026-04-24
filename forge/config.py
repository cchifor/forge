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
PLUGIN_LANGUAGES: dict[str, _PluginLanguage] = {}


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


def register_backend_language(value: str) -> _PluginLanguage:
    """Register a plugin language value. Returns the sentinel member."""
    if value not in PLUGIN_LANGUAGES:
        PLUGIN_LANGUAGES[value] = _PluginLanguage(value)
    return PLUGIN_LANGUAGES[value]


def resolve_backend_language(value: str) -> BackendLanguage | _PluginLanguage:
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


def _default_toolchain_factory() -> Any:
    """Lazy import to break the config → toolchains cycle.

    ``forge.toolchains`` depends only on ``forge.errors``, not ``forge.config``,
    so this factory runs at ``BackendSpec(...)`` instantiation time (well
    after import) without creating an import cycle.
    """
    from forge.toolchains import NOOP_TOOLCHAIN  # noqa: PLC0415

    return NOOP_TOOLCHAIN


@dataclass(frozen=True)
class BackendSpec:
    """Static metadata for a backend language: template, prompts, version field.

    Adding a 4th backend means adding one entry here plus one Copier template
    directory under `forge/templates/services/`. The CLI prompt loop, generator
    dispatch, and variable-mapper context builder all read from this registry.

    ``toolchain`` carries the per-language install / verify / post-generate
    hooks previously hardcoded in ``generator.py``'s language dispatch.
    Plugin-registered backends attach their own implementation — see
    ``forge.toolchains.BackendToolchain`` Protocol. Typed as ``Any`` to keep
    ``forge.config`` free of the ``forge.toolchains`` import (the factory
    resolves it lazily).
    """

    template_dir: str  # path under forge/templates/, e.g. "services/python-service-template"
    display_label: str  # shown in CLI prompts and log messages
    version_field: str  # name of the BackendConfig attribute holding the version
    version_choices: tuple[str, ...]  # interactive prompt choices, first is default
    toolchain: Any = field(default_factory=_default_toolchain_factory)


def _python_toolchain_factory() -> Any:
    from forge.toolchains.python import PYTHON_TOOLCHAIN  # noqa: PLC0415

    return PYTHON_TOOLCHAIN


def _node_toolchain_factory() -> Any:
    from forge.toolchains.node import NODE_TOOLCHAIN  # noqa: PLC0415

    return NODE_TOOLCHAIN


def _rust_toolchain_factory() -> Any:
    from forge.toolchains.rust import RUST_TOOLCHAIN  # noqa: PLC0415

    return RUST_TOOLCHAIN


# BACKEND_REGISTRY keys are either real ``BackendLanguage`` members or
# ``_PluginLanguage`` sentinels — both share the ``.value`` attribute so
# downstream code can treat them uniformly.
BACKEND_REGISTRY: dict[BackendLanguage | _PluginLanguage, BackendSpec] = {
    BackendLanguage.PYTHON: BackendSpec(
        template_dir="services/python-service-template",
        display_label="Python (FastAPI)",
        version_field="python_version",
        version_choices=("3.13", "3.12", "3.11"),
        toolchain=_python_toolchain_factory(),
    ),
    BackendLanguage.NODE: BackendSpec(
        template_dir="services/node-service-template",
        display_label="Node.js (Fastify)",
        version_field="node_version",
        version_choices=("22", "20", "18"),
        toolchain=_node_toolchain_factory(),
    ),
    BackendLanguage.RUST: BackendSpec(
        template_dir="services/rust-service-template",
        display_label="Rust (Axum)",
        version_field="rust_edition",
        version_choices=("2024", "2021"),
        toolchain=_rust_toolchain_factory(),
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

    @property
    def backend_mode(self) -> str:
        """Layer discriminator for backend generation.

        ``"generate"`` (default) runs the per-backend Copier template +
        fragment pipeline for every entry in ``backends``. ``"none"``
        skips backend generation entirely — the project becomes a
        frontend (+ infra) pointing at an externally-hosted API.

        Read from ``self.options["backend.mode"]``; defaults to
        ``"generate"`` when the option isn't set, matching the Option's
        registered default and preserving pre-Phase-A behavior.
        """
        return str(self.options.get("backend.mode", "generate"))

    @property
    def frontend_api_target_url(self) -> str:
        """External API base URL used when ``backend_mode == "none"``.

        Phase B2 canonical path: ``frontend.api_target.url``. The Phase
        A path ``frontend.api_target_url`` is a deprecated alias — the
        resolver rewrites it transparently, but the raw ``options``
        dict on ``ProjectConfig`` may still contain the alias form
        (user-supplied, pre-resolve). Check both.
        """
        return str(
            self.options.get("frontend.api_target.url")
            or self.options.get("frontend.api_target_url")
            or ""
        )

    @property
    def frontend_mode(self) -> str:
        """Layer discriminator for frontend generation.

        Returns ``"generate"`` / ``"external"`` / ``"none"``. Coherent
        with ``FrontendConfig.framework == FrontendFramework.NONE``:
        both surfaces get harmonised via
        ``FrontendConfig.effective_mode`` at the framework level, and
        at the project level via ``_validate_layer_modes``.
        """
        return str(self.options.get("frontend.mode", "generate"))

    @property
    def frontend_api_target_type(self) -> str:
        """Whether the frontend targets a local or external API.

        ``"local"`` (default) — Vite proxy routes to the Docker-internal
        backend. ``"external"`` — the generated app points at
        ``frontend_api_target_url`` directly.
        """
        return str(self.options.get("frontend.api_target.type", "local"))

    @property
    def database_mode(self) -> str:
        """Layer discriminator for database provisioning.

        ``"generate"`` (default) provisions PostgreSQL in docker-compose
        and scaffolds the full DB stack in Python backends. ``"none"``
        skips the postgres service entirely — appropriate for
        stateless services or projects whose persistence lives outside
        the generated stack.

        Phase B1 introduces this at the compose-rendering level; a
        future Python-template ``database_strip`` fragment will remove
        alembic + SQLAlchemy imports for a fully stateless backend.
        """
        return str(self.options.get("database.mode", "generate"))

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
        self._validate_layer_modes()
        self._resolve_once()

    def _validate_layer_modes(self) -> None:
        """Enforce coherence between ``backend.mode`` and the rest of the config.

        Phase A of the discriminated-union rollout. Rules:

        * ``backend.mode=none`` with a non-empty ``backends`` list is a
          contradiction — the user wants no backends, but provided some.
        * ``backend.mode=generate`` with no backends AND no frontend is
          an empty project — nothing to scaffold.
        * ``backend.mode=none`` with a configured frontend requires
          ``frontend.api_target.url`` to be set. Without an external
          URL the generated Vite proxy / ``.env.development`` have
          nowhere to point.

        Runs *after* ``_validate_options`` so unknown/invalid option paths
        surface with the existing close-match hint first.
        """
        mode = self.backend_mode
        has_frontend = bool(
            self.frontend and self.frontend.framework != FrontendFramework.NONE
        )
        if mode == "none" and self.backends:
            raise ValueError(
                f"backend.mode=none is incompatible with {len(self.backends)} "
                "configured backend(s). Either remove the backends list or "
                "set backend.mode=generate."
            )
        if mode == "generate" and not self.backends and not has_frontend:
            raise ValueError(
                "Empty project: no backends to generate and no frontend "
                "configured. Set at least one backend, a frontend, or use "
                "backend.mode=none alongside frontend.api_target.url=<URL>."
            )
        if mode == "none" and has_frontend and not self.frontend_api_target_url:
            raise ValueError(
                "backend.mode=none with a frontend framework requires "
                "frontend.api_target.url to be set (the external API base "
                "URL the generated app will point at)."
            )
        self._validate_database_mode()
        self._validate_frontend_mode_coherence()

    def _validate_frontend_mode_coherence(self) -> None:
        """Reject contradictions between ``frontend.mode`` and the
        ``FrontendFramework`` on ``FrontendConfig``.

        Phase B2 introduces two surfaces for the same decision:
        ``options["frontend.mode"]`` (new) and
        ``FrontendConfig.framework == NONE`` (pre-existing). They must
        agree. Also: ``frontend.api_target.type="external"`` requires
        ``frontend.api_target.url`` to be non-empty.
        """
        mode = self.frontend_mode
        framework_is_none = (
            self.frontend is None
            or self.frontend.framework == FrontendFramework.NONE
        )
        if mode == "none" and not framework_is_none:
            raise ValueError(
                f"frontend.mode=none contradicts frontend.framework="
                f"{self.frontend.framework.value!r}. Either remove the "
                "frontend config or set frontend.mode=generate."
            )
        if mode != "none" and framework_is_none and mode != "generate":
            # mode="external" with framework=NONE is nonsensical — there's
            # no app being generated to point at the external URL.
            raise ValueError(
                f"frontend.mode={mode!r} requires a frontend framework. "
                "Set frontend.framework=vue/svelte/flutter or switch to "
                "frontend.mode=none."
            )
        if self.frontend_api_target_type == "external" and not self.frontend_api_target_url:
            raise ValueError(
                "frontend.api_target.type='external' requires "
                "frontend.api_target.url to be a non-empty URL."
            )

    def _validate_database_mode(self) -> None:
        """Reject ``database.mode=none`` when DB-dependent options are on.

        Phase B1 — the compose-level strip works, but the Python template
        still emits alembic + SQLAlchemy code. Options that *write* to
        the DB (conversation history, RAG vector store, attachments
        metadata, SQLAdmin panel, webhooks registry) must be explicitly
        turned off before the user can flip to stateless mode.

        The errors name the specific options so the user can fix them
        one at a time rather than hunting through the full catalogue.
        """
        if self.database_mode != "none":
            return
        conflicts: list[str] = []
        if self.options.get("conversation.persistence"):
            conflicts.append("conversation.persistence=true")
        rag_backend = self.options.get("rag.backend", "none")
        if rag_backend and rag_backend != "none":
            conflicts.append(f"rag.backend={rag_backend!r}")
        if self.options.get("chat.attachments"):
            conflicts.append("chat.attachments=true")
        if self.options.get("agent.streaming"):
            conflicts.append("agent.streaming=true")
        if self.options.get("agent.llm"):
            conflicts.append("agent.llm=true")
        if self.options.get("platform.admin"):
            conflicts.append("platform.admin=true")
        if self.options.get("platform.webhooks"):
            conflicts.append("platform.webhooks=true")
        if conflicts:
            raise ValueError(
                "database.mode=none is incompatible with the following "
                f"DB-backed options: {', '.join(conflicts)}. "
                "Either switch to database.mode=generate or disable these "
                "options."
            )

    def _validate_options(self) -> None:
        """Check every option path is registered and each value is valid.

        Same close-match suggestion pattern the CLI uses for typos.
        Delegates shape checks (type matching, enum bounds, min/max) to
        ``Option.validate_value``.

        Phase B2: accepts deprecated aliases too. ``resolve_alias``
        maps a user-supplied alias path to its canonical Option so
        validation runs against the real spec (and a deprecation
        warning surfaces later in ``_apply_option_defaults`` when the
        resolver rewrites the path).
        """
        import difflib  # noqa: PLC0415

        from forge.options import OPTION_REGISTRY, resolve_alias  # noqa: PLC0415

        for path, value in self.options.items():
            canonical = resolve_alias(path) or path
            spec = OPTION_REGISTRY.get(canonical)
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
        """Aggregate deduplicated features across backends and frontend, preserving order.

        Backend features come first (each backend's CRUD entities drive
        the generated API routes + ORM models); frontend-only features
        top up when the project has no local backend (Phase A:
        ``backend.mode=none`` scenarios). Order-preserving dedup keeps
        the output stable for templates that emit UI route tables.
        """
        seen: set[str] = set()
        features: list[str] = []
        for bc in self.backends:
            for f in bc.features:
                if f not in seen:
                    seen.add(f)
                    features.append(f)
        if self.frontend:
            for f in self.frontend.features:
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
