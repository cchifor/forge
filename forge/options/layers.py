"""Layer composition (Phases A–C) — discriminated-union mode options.

These options control *what* forge generates, not *which feature*. They
sit above the feature registry: e.g. ``backend.mode=none`` short-circuits
the per-backend loop in ``generator.py``, which inhibits every
backend-scoped fragment's ``target_backends`` expansion. ``enables``
stays empty — the discriminator orchestrates generation, it doesn't
enable a fragment bundle.

The four layer discriminators (``backend.mode`` / ``database.mode`` /
``frontend.mode`` / ``agent.mode``) share the same ENUM shape + empty
``enables`` contract. ``tests/test_phase_c.py::TestLayerModeParity``
locks that invariant in. ``agent.mode`` lives in ``forge/options/agent``
to keep every ``agent.*`` knob in one file.

The Phase A flat ``frontend.api_target_url`` is preserved as a
deprecated alias of ``frontend.api_target.url`` (see the ``aliases=``
+ ``deprecated_since=`` pair below). The resolver rewrites the alias
transparently at ``_apply_option_defaults`` time.
"""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="backend.mode",
        type=OptionType.ENUM,
        default="generate",
        options=("generate", "none"),
        summary="Whether forge scaffolds backend services for this project.",
        description="""\
Layer discriminator. ``generate`` (default) runs the per-backend Copier
template + fragment pipeline for every entry in ``backends``. ``none``
skips backend generation entirely — useful for frontend-only projects
that point at an already-deployed API (set ``frontend.api_target.url``
to that API's base URL).

With ``mode=none`` the project still gets a docker-compose.yml (frontend
+ traefik + optional keycloak) but no ``services/`` directory.""",
        category=FeatureCategory.PLATFORM,
    )
)


register_option(
    Option(
        path="frontend.mode",
        type=OptionType.ENUM,
        default="generate",
        options=("generate", "external", "none"),
        summary="Whether forge scaffolds a frontend for this project.",
        description="""\
Layer discriminator for the frontend. ``generate`` (default) runs the
per-framework Copier template. ``external`` is reserved for future
work where forge renders a thin wrapper that points at an existing
deployed frontend. ``none`` skips frontend generation entirely — use
when you only want a backend + infra stack.

Note on compatibility with ``FrontendFramework.NONE``: the two paths
converge via ``FrontendConfig.effective_mode``. Setting
``frontend.mode="none"`` is equivalent to omitting the frontend entry
or setting ``framework=FrontendFramework.NONE``.""",
        category=FeatureCategory.PLATFORM,
    )
)


register_option(
    Option(
        path="frontend.api_target.type",
        type=OptionType.ENUM,
        default="local",
        options=("local", "external"),
        summary="Whether the frontend's API client targets a local or external backend.",
        description="""\
Paired with ``frontend.api_target.url``. ``local`` (default) — the
generated Vite proxy forwards ``/api/*`` to the Docker-internal
backend service (preserves Phase A + pre-Phase A behavior).
``external`` — the frontend points at ``frontend.api_target.url``
directly; Vite proxy becomes a no-op.

B2 replaces the Phase A flat ``frontend.api_target_url`` option with
this discriminated pair. The old path is preserved as a deprecated
alias of ``frontend.api_target.url`` — pre-existing configs continue
to work unchanged.""",
        category=FeatureCategory.PLATFORM,
    )
)


register_option(
    Option(
        path="frontend.api_target.url",
        type=OptionType.STR,
        default="",
        summary="External API base URL (when frontend.api_target.type=external).",
        description="""\
Base URL the generated frontend talks to when
``frontend.api_target.type=external`` or when ``backend.mode=none``.
The value populates ``api_base_url`` / ``api_proxy_target`` /
``env_api_base_url`` via ``variable_mapper``.

Empty string means the template falls back to local inference
(compute the URL from the first backend's port).""",
        category=FeatureCategory.PLATFORM,
        aliases=("frontend.api_target_url",),
        deprecated_since="1.2.0",
    )
)


register_option(
    Option(
        path="database.mode",
        type=OptionType.ENUM,
        default="generate",
        options=("generate", "none"),
        summary="Whether the generated stack provisions a local database.",
        description="""\
Layer discriminator. ``generate`` (default) provisions PostgreSQL in
``docker-compose.yml`` and scaffolds the full DB stack in Python
backends (alembic, SQLAlchemy session, connection pool). ``none``
skips the postgres service + migrate containers entirely — suitable
for stateless services whose persistence lives elsewhere (external
RDBMS, API-only projects).

Incompatible with DB-backed options: ``conversation.persistence``,
``rag.backend != none``, ``chat.attachments``, ``agent.llm``. The
resolver rejects these combinations at config-validation time.""",
        category=FeatureCategory.PLATFORM,
    )
)


register_option(
    Option(
        path="database.engine",
        type=OptionType.ENUM,
        default="postgres",
        options=("postgres",),
        summary="Database engine used when database.mode=generate.",
        description="""\
Single-value enum today (postgres) — kept as an ENUM rather than a bool
so adding MySQL / SQLite / CockroachDB in a future phase doesn't
break existing ``forge.toml`` files. Mirrors the
``middleware.correlation_id`` always-on enum pattern.""",
        category=FeatureCategory.PLATFORM,
    )
)
