"""ProjectConfig — top-level config dataclass + validators.

ProjectConfig is the user-facing configuration root. It owns the list
of backends, the optional frontend, the Keycloak switch, and the typed
:attr:`options` mapping that drives the option resolver. Most of this
module is the ``_validate_*`` family that runs in :meth:`validate` —
they're broken out as private methods so each invariant has a focused
home rather than living inside one giant validate() body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from forge.config._backend import BackendConfig
from forge.config._frontend import FRONTEND_RESERVED, FrontendConfig, FrontendFramework
from forge.config._validators import TRAEFIK_DASHBOARD_PORT, validate_port


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
        """Run all ProjectConfig invariants.

        Called once from the CLI builder and the interactive prompt
        after configuration is fully assembled. Split into two phases:

        1. **Structural invariants** (project name, backend / frontend
           sanity, port uniqueness, feature names). Would also be safe
           in ``__post_init__`` but callers that mutate ``options``
           between construction and validation rely on validation
           running once, after all the edits.
        2. **Option-dependent invariants** (unknown options, layer
           modes, database mode). Runs after option defaults have been
           layered in, which is why this lives here rather than
           ``__post_init__``.

        Raises ``ValueError`` with a specific, actionable message on
        the first violation found.
        """
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
        has_frontend = bool(self.frontend and self.frontend.framework != FrontendFramework.NONE)
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
        # Inline the narrowing rather than caching `framework_is_none` so ty
        # can see ``self.frontend is not None`` on the contradiction branch.
        if (
            mode == "none"
            and self.frontend is not None
            and self.frontend.framework != FrontendFramework.NONE
        ):
            raise ValueError(
                "frontend.mode=none contradicts frontend.framework="
                f"{self.frontend.framework.value!r}. Either remove the "
                "frontend config or set frontend.mode=generate."
            )
        framework_is_none = (
            self.frontend is None or self.frontend.framework == FrontendFramework.NONE
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
