"""Configuration dataclasses for forge."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from enum import Enum


class BackendLanguage(Enum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"


class FrontendFramework(Enum):
    VUE = "vue"
    SVELTE = "svelte"
    FLUTTER = "flutter"
    NONE = "none"


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


BACKEND_REGISTRY: dict[BackendLanguage, BackendSpec] = {
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
        traefik_dashboard_port = 8888
        if traefik_dashboard_port in ports:
            raise ValueError(
                f"Port {traefik_dashboard_port} (Traefik dashboard) "
                f"conflicts with {ports[traefik_dashboard_port]}."
            )
        ports[traefik_dashboard_port] = "Traefik dashboard"
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
