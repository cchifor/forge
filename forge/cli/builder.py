"""Build a ``ProjectConfig`` from CLI args merged with config-file values.

The ``_Resolver`` bundles the parsed argparse namespace with the loaded
config dict so helpers can look up a value in a single call: CLI flag
wins over config-file value wins over default.
"""

from __future__ import annotations

import argparse
from typing import Any, cast

from forge.cli.parser import FRAMEWORK_MAP
from forge.config import (
    DEFAULT_REALM,
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
    keycloak_client_id_from,
)
from forge.options import OPTION_REGISTRY, OptionType


class _Resolver:
    """Bundles `args` + parsed config file for the duration of _build_config.

    Replaces threading `(args, cfg, ...)` through every helper and drops the
    first two positional arguments from each lookup. Call-sites go from
    `_get(args, "frontend_port", cfg, "frontend", "server_port", default=5173)`
    to `r.get("frontend_port", "frontend", "server_port", default=5173)`.
    """

    def __init__(self, args: argparse.Namespace, cfg: dict[str, Any]) -> None:
        self.args = args
        self.cfg = cfg

    def get(self, flag: str, *keys: str, default: Any = None) -> Any:
        """Resolve a value: CLI flag > config file > default."""
        val = getattr(self.args, flag, None)
        if val is not None:
            return val
        node: Any = self.cfg
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
            else:
                return default
        return node if node is not None else default


def _normalize_features(raw: Any, default: list[str] | None = None) -> list[str]:
    """Coerce CLI/config feature input (list or comma-string) to a clean list."""
    if raw is None:
        return list(default) if default else []
    if isinstance(raw, list):
        return [str(f).strip() for f in raw if str(f).strip()]
    return [f.strip() for f in str(raw).split(",") if f.strip()]


def _build_backends_from_cfg(
    r: _Resolver, project_name: str, description: str
) -> list[BackendConfig]:
    """Build backend list from CLI args + config file.

    Supports both `backends:` (list) and `backend:` (single) for backward compatibility.
    """
    backends_raw = r.cfg.get("backends")
    if isinstance(backends_raw, list) and backends_raw:
        backends: list[BackendConfig] = []
        for i, raw in enumerate(backends_raw):
            if not isinstance(raw, dict):
                continue
            be_cfg = cast("dict[str, Any]", raw)
            lang = be_cfg.get("language", "python")
            language = (
                BackendLanguage(lang)
                if lang in ("python", "node", "rust")
                else BackendLanguage.PYTHON
            )
            backends.append(
                BackendConfig(
                    name=be_cfg.get("name", f"backend-{i}"),
                    project_name=project_name,
                    language=language,
                    description=be_cfg.get("description", description),
                    features=_normalize_features(be_cfg.get("features"), default=["items"]),
                    python_version=be_cfg.get("python_version", "3.13"),
                    node_version=be_cfg.get("node_version", "22"),
                    rust_edition=be_cfg.get("rust_edition", "2024"),
                    server_port=be_cfg.get("server_port", 5000 + i),
                )
            )
        return backends

    # Single backend (backward compat for `backend:` shape and CLI-only invocations)
    lang_str = r.get("backend_language", "backend", "language", default="python")
    language = (
        BackendLanguage(lang_str)
        if lang_str in ("python", "node", "rust")
        else BackendLanguage.PYTHON
    )
    return [
        BackendConfig(
            name=r.get("backend_name", "backend", "name", default="backend"),
            project_name=project_name,
            language=language,
            description=description,
            features=_normalize_features(
                r.get("features", "backend", "features", default=None),
                default=["items"],
            ),
            python_version=r.get("python_version", "backend", "python_version", default="3.13"),
            node_version=r.get("node_version", "backend", "node_version", default="22"),
            rust_edition=r.get("rust_edition", "backend", "rust_edition", default="2024"),
            server_port=r.get("backend_port", "backend", "server_port", default=5000),
        )
    ]


def _build_frontend_from_cfg(
    r: _Resolver, project_name: str, description: str
) -> tuple[FrontendConfig | None, bool]:
    """Build optional frontend config; returns (frontend, include_auth)."""
    fw_str = r.get("frontend", "frontend", "framework", default="none")
    framework = FRAMEWORK_MAP.get(fw_str, FrontendFramework.NONE)
    if framework == FrontendFramework.NONE:
        return None, False

    include_auth = r.get("include_auth", "frontend", "include_auth", default=True)
    frontend = FrontendConfig(
        framework=framework,
        project_name=project_name,
        description=description,
        author_name=r.get("author_name", "frontend", "author_name", default="Your Name"),
        package_manager=r.get("package_manager", "frontend", "package_manager", default="npm"),
        include_auth=include_auth,
        include_chat=r.get("include_chat", "frontend", "include_chat", default=False),
        include_openapi=r.get("include_openapi", "frontend", "include_openapi", default=False),
        server_port=r.get("frontend_port", "frontend", "server_port", default=5173),
        default_color_scheme=r.get(
            "color_scheme", "frontend", "default_color_scheme", default="blue"
        ),
        org_name=r.get("org_name", "frontend", "org_name", default="com.example"),
        generate_e2e_tests=r.get(
            "generate_e2e_tests", "frontend", "generate_e2e_tests", default=True
        ),
    )
    return frontend, include_auth


def _flatten_nested(raw: Any, prefix: str = "") -> dict[str, Any]:
    """Turn nested dict form into dotted-key form.

    YAML users can write
        options:
          middleware:
            rate_limit: false
    which parses to ``{"middleware": {"rate_limit": False}}``. This
    function flattens it into ``{"middleware.rate_limit": False}`` so the
    rest of the pipeline only ever sees dotted keys. Values that are
    already scalars / lists pass through unchanged.
    """
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten_nested(value, prefix=path))
        else:
            out[path] = value
    return out


def _coerce_set_value(path: str, raw: str) -> Any:
    """Convert a ``--set PATH=VALUE`` string to the Option's native type."""
    opt = OPTION_REGISTRY.get(path)
    if opt is None:
        return raw
    if opt.type is OptionType.BOOL:
        lower = raw.strip().lower()
        if lower in ("true", "1", "yes", "on"):
            return True
        if lower in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"--set {path}=<value>: expected true/false, got {raw!r}")
    if opt.type is OptionType.INT:
        try:
            return int(raw)
        except ValueError as e:
            raise ValueError(f"--set {path}=<value>: expected integer, got {raw!r}") from e
    if opt.type is OptionType.ENUM and opt.options:
        sample = opt.options[0]
        if isinstance(sample, bool):
            lower = raw.strip().lower()
            if lower in ("true", "false"):
                return lower == "true"
        if isinstance(sample, int) and not isinstance(sample, bool):
            try:
                return int(raw)
            except ValueError:
                return raw
    if opt.type is OptionType.LIST:
        return [v.strip() for v in raw.split(",") if v.strip()]
    return raw


def _build_options(args: argparse.Namespace, cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge YAML ``options:`` block with ``--set`` repeats."""
    options: dict[str, Any] = {}

    yaml_block = cfg.get("options")
    if isinstance(yaml_block, dict):
        options.update(_flatten_nested(yaml_block))

    for entry in getattr(args, "set_options", None) or []:
        if "=" not in entry:
            raise ValueError(f"--set expects PATH=VALUE, got {entry!r}")
        path, raw_value = entry.split("=", 1)
        options[path.strip()] = _coerce_set_value(path.strip(), raw_value.strip())

    return options


def _build_config(args: argparse.Namespace, cfg: dict[str, Any]) -> ProjectConfig:
    """Build ProjectConfig from CLI args merged with config file."""
    r = _Resolver(args, cfg)
    project_name = r.get("project_name", "project_name", default="My Platform")
    description = r.get("description", "description", default="A full-stack application")
    # Fall back to the cfg file's ``output_dir`` when args has no value (e.g.
    # the matrix runner seeds ``output_dir`` via cfg with a synthetic argparse
    # namespace). The CLI argparse default of ``"."`` keeps the normal path
    # unchanged.
    output_dir = r.get("output_dir", "output_dir", default=".")

    backends = _build_backends_from_cfg(r, project_name, description)
    frontend, include_auth = _build_frontend_from_cfg(r, project_name, description)
    options = _build_options(args, cfg)

    include_keycloak = include_auth
    keycloak_port = r.get("keycloak_port", "keycloak", "port", default=18080)
    kc_realm = r.get("keycloak_realm", "keycloak", "realm", default=DEFAULT_REALM)
    kc_client_id = r.get(
        "keycloak_client_id",
        "keycloak",
        "client_id",
        default=keycloak_client_id_from(project_name),
    )

    if frontend and include_keycloak:
        frontend.keycloak_url = f"http://localhost:{keycloak_port}"
        frontend.keycloak_realm = kc_realm
        frontend.keycloak_client_id = kc_client_id

    return ProjectConfig(
        project_name=project_name,
        output_dir=str(output_dir),
        backends=backends,
        frontend=frontend,
        include_keycloak=include_keycloak,
        keycloak_port=keycloak_port,
        options=options,
    )
