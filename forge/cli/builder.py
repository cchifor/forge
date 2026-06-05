"""Build a ``ProjectConfig`` from CLI args merged with config-file values.

The ``_Resolver`` bundles the parsed argparse namespace with the loaded
config dict so helpers can look up a value in a single call: CLI flag
wins over config-file value wins over default.

Initiative #5 — the CLI sometimes coerces user-set fields silently
(e.g. ``auth.mode`` flips to ``"none"`` when Keycloak is disabled).
``_build_config`` accepts an optional ``mutations`` collector so the
caller can surface those rewrites in the JSON envelope under
``hidden_mutations``.
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
from forge.reports import HiddenMutation


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


def _backend_language(value: object) -> BackendLanguage:
    """Resolve a backend language string, erroring on unknown values.

    An absent key defaults to ``"python"`` at the call sites; a *present* but
    unknown value (e.g. ``language: cobol``) is a user mistake worth surfacing
    rather than silently coercing to Python.
    """
    if value in ("python", "node", "rust"):
        return BackendLanguage(value)
    raise ValueError(f"Unknown backend language {value!r}; valid languages are python, node, rust.")


def _build_backends_from_cfg(
    r: _Resolver, project_name: str, description: str
) -> list[BackendConfig]:
    """Build backend list from CLI args + config file.

    Supports both `backends:` (list) and `backend:` (single) for backward compatibility.
    """
    backends_raw = r.cfg.get("backends")
    if isinstance(backends_raw, list):
        # An explicit list — possibly empty — is the user expressing intent.
        # An empty list means "frontend-only project (backend.mode=none)";
        # ProjectConfig.validate() enforces coherence with options. Only the
        # *absent* key falls through to the single-backend placeholder below.
        backends: list[BackendConfig] = []
        for i, raw in enumerate(backends_raw):
            if not isinstance(raw, dict):
                continue
            be_cfg = cast("dict[str, Any]", raw)
            language = _backend_language(be_cfg.get("language", "python"))
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
                    sdk_consumption=be_cfg.get("sdk_consumption"),
                )
            )
        return backends

    # Single backend (backward compat for `backend:` shape and CLI-only invocations)
    language = _backend_language(r.get("backend_language", "backend", "language", default="python"))
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
        # ``api_base_url`` and ``api_proxy_target`` are first-class
        # FrontendConfig fields (see ``forge/config/_frontend.py:171``)
        # that the cfg dict couldn't reach before. Pipe them through so
        # YAML can express ``frontend.api_base_url`` directly — preserving
        # the dataclass contract for consumers that read it (the Flutter
        # post-generate task today; future Vue/Svelte direct consumers).
        # Note: the Vue/Svelte variable mapper currently reads the
        # equivalent option path ``frontend.api_target.url`` instead.
        api_base_url=r.get("api_base_url", "frontend", "api_base_url", default=""),
        api_proxy_target=r.get("api_proxy_target", "frontend", "api_proxy_target", default=""),
        generate_e2e_tests=r.get(
            "generate_e2e_tests", "frontend", "generate_e2e_tests", default=True
        ),
        layout=r.get("layout", "frontend", "layout", default="sidebar"),
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


def _build_config(
    args: argparse.Namespace,
    cfg: dict[str, Any],
    *,
    mutations: list[HiddenMutation] | None = None,
) -> ProjectConfig:
    """Build ProjectConfig from CLI args merged with config file.

    ``mutations`` is an optional collector for CLI-side silent
    rewrites; see :class:`forge.reports.HiddenMutation`. Pass an
    empty list to capture every coercion (``auth.mode`` flip when
    Keycloak is disabled, etc.) so the caller can surface them in
    the JSON envelope. ``None`` (the default) preserves the pre-#5
    behaviour where rewrites were silent.
    """
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

    # ``include_keycloak`` follows ``frontend.include_auth`` by default,
    # but config files (and matrix scenarios) can override at the top
    # level — e.g. a headless service that wants the keycloak sidecar
    # for S2S token issuance even though there's no SPA. CLI flag wins
    # over config-file value, which wins over the frontend-derived default.
    include_keycloak = r.get("include_keycloak", "include_keycloak", default=include_auth)
    # ``auth.mode=generate`` enables the platform-auth stack, which needs
    # both Keycloak (for human login) and Redis (for BFF sessions + gatekeeper).
    # When the project disables Keycloak the platform-auth model can't run —
    # specifically, the platform_auth_gatekeeper fragment's compose entry
    # declares ``depends_on: { redis, keycloak }`` and base
    # docker-compose.yml.j2 only renders those services under ``include_keycloak``.
    # Without this coercion, ``docker compose up`` fails validation with
    # ``service "gatekeeper" depends on undefined service "redis"``.
    #
    # Initiative #5 — snapshot which option paths were user-set *before*
    # this coercion. The result drives the parallel ``option_origins``
    # dict on ProjectConfig so the report can distinguish a real user
    # choice from a CLI-injected default like the one below. Without
    # this snapshot, ``options["auth.mode"] = "none"`` would leak into
    # ``option_origins`` as ``"user"`` even when the user never touched
    # the option (the resolver would dutifully record it that way).
    user_set_paths = set(options)
    auth_mode_before = options.get("auth.mode", "generate")
    if not include_keycloak and auth_mode_before != "none":
        options["auth.mode"] = "none"
        # Surface the coercion to JSON callers via the mutations collector.
        # Agents driving forge headlessly need to know the auth.mode value
        # they asked for isn't what generation acted on; without this they
        # end up debugging "why is there no platform-auth stack" against a
        # manifest that records ``auth.mode = "none"`` because of the
        # coercion (not because they set it).
        if mutations is not None:
            mutations.append(
                HiddenMutation(
                    path="auth.mode",
                    previous=auth_mode_before,
                    current="none",
                    reason=(
                        "Keycloak is disabled (include_keycloak=False); "
                        "platform-auth requires both Keycloak and Redis to "
                        "run, so auth.mode was coerced to 'none'."
                    ),
                )
            )

    # Build the option_origins dict the resolver consumes. Paths the user
    # set before the auth.mode coercion are "user"; anything the CLI
    # injected (auth.mode flipped from default) is "default". The resolver
    # in capability_resolver layers in its own defaults on top of this
    # snapshot.
    option_origins: dict[str, str] = {
        path: ("user" if path in user_set_paths else "default") for path in options
    }
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

    # Layered-component selection: a top-level `components: [Name, ...]` list in
    # the config file (additive; absent ⇒ flat option/fragment generation).
    # Fail loud on a malformed shape rather than silently coercing
    # (`components: StatCard` → [] or `[123]` → ["123"]).
    components_raw = r.cfg.get("components")
    if components_raw is None:
        components: list[str] = []
    elif isinstance(components_raw, list) and all(isinstance(c, str) for c in components_raw):
        # isinstance in the comprehension lets the type checker narrow to str.
        components = [c for c in components_raw if isinstance(c, str)]
    else:
        raise ValueError(
            "config `components` must be a list of component-name strings, got "
            f"{type(components_raw).__name__}."
        )

    return ProjectConfig(
        project_name=project_name,
        output_dir=str(output_dir),
        backends=backends,
        frontend=frontend,
        include_keycloak=include_keycloak,
        keycloak_port=keycloak_port,
        options=options,
        option_origins=option_origins,
        components=components,
        component_origins={c: "user" for c in components},
    )
