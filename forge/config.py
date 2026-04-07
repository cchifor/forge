"""Configuration dataclasses for forge-cli."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BackendLanguage(Enum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"


class FrontendFramework(Enum):
    VUE = "vue"
    SVELTE = "svelte"
    FLUTTER = "flutter"
    NONE = "none"


# Reserved feature names for frontend templates
FRONTEND_RESERVED = frozenset({
    "auth", "home", "profile", "settings", "chat", "core", "shared",
    "shell", "dashboard", "tasks", "app", "test", "lib", "routes", "api",
})


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
    project_name: str
    language: BackendLanguage = BackendLanguage.PYTHON
    description: str = "A microservice"
    python_version: str = "3.13"
    node_version: str = "22"
    rust_edition: str = "2024"
    server_port: int = 5000

    def validate(self) -> None:
        validate_port(self.server_port, "Backend port")


@dataclass
class FrontendConfig:
    framework: FrontendFramework
    project_name: str
    description: str = "A frontend application"
    features: list[str] = field(default_factory=lambda: ["items"])
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
                raise ValueError(
                    f"Feature '{f}' is reserved in the frontend template."
                )
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
    backend: Optional[BackendConfig] = None
    frontend: Optional[FrontendConfig] = None
    include_keycloak: bool = False
    keycloak_port: int = 8080

    def validate(self) -> None:
        if not self.project_name.strip():
            raise ValueError("Project name cannot be empty.")
        if self.backend:
            self.backend.validate()
        if self.frontend:
            self.frontend.validate()
        if self.include_keycloak:
            validate_port(self.keycloak_port, "Keycloak port")

        # Check for port collisions on host-mapped ports
        ports: dict[int, str] = {}
        if self.backend:
            ports[self.backend.server_port] = "backend"
        if self.frontend and self.frontend.framework != FrontendFramework.NONE:
            if self.frontend.framework != FrontendFramework.FLUTTER:
                p = self.frontend.server_port
                if p in ports:
                    raise ValueError(
                        f"Port {p} is used by both frontend and {ports[p]}."
                    )
                ports[p] = "frontend"
        db_port = 5432
        if db_port in ports:
            raise ValueError(
                f"Port {db_port} (PostgreSQL) conflicts with {ports[db_port]}."
            )
        ports[db_port] = "postgres"
        if self.include_keycloak:
            # Traefik dashboard uses port 8888
            traefik_dashboard_port = 8888
            if traefik_dashboard_port in ports:
                raise ValueError(
                    f"Port {traefik_dashboard_port} (Traefik dashboard) "
                    f"conflicts with {ports[traefik_dashboard_port]}."
                )
            ports[traefik_dashboard_port] = "Traefik dashboard"
            if self.keycloak_port in ports:
                raise ValueError(
                    f"Port {self.keycloak_port} (Keycloak) conflicts "
                    f"with {ports[self.keycloak_port]}."
                )

    @property
    def project_slug(self) -> str:
        return self.project_name.lower().replace(" ", "_").replace("-", "_")

    @property
    def backend_slug(self) -> str:
        """Fixed directory name for the generated backend service."""
        return "backend"

    @property
    def frontend_slug(self) -> str:
        """Fixed directory name for the generated frontend application."""
        return "frontend"
