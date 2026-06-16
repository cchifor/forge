"""Pydantic v2 model for the orchestration boundary (Theme 5-C1).

`ProjectConfig.options` is a ``dict[str, Any]`` today: every consumer
threads it through stringly-typed lookups (``options.get("backend.mode",
"generate")``). Theme 5 replaces that surface with a typed model whose
**layer-mode fields are discriminated unions** — adding a backend mode
or an agent mode means adding a sub-model with a ``mode`` literal, not
sprinkling string comparisons across the codebase.

This module is **introduced alongside** the legacy dict in C1; the
legacy dict survives unchanged until C3. The win of C1 is that

1. The shape of the orchestration config is captured in one type that
   readers can grep / type-check / introspect.
2. ``from_legacy_options`` becomes the single conversion point —
   anywhere we want to consume a typed config we go through this
   converter, and anywhere we still need the dict we go through the
   inverse ``to_legacy_options``.
3. Pydantic's ``ValidationError`` surfaces shape mismatches with a
   field path rather than a stringly-typed ``ValueError("Unknown
   option 'backed.mode'")`` after an option lookup.

Design notes:

* Four layer-mode unions: ``BackendConfigT``, ``FrontendConfigT``,
  ``DatabaseConfigT``, ``AgentConfigT``. Each is an
  ``Annotated[Union[..., ...], Field(discriminator="mode")]``.
* Non-layer options live on ``TypedConfig.other`` as a typed mapping
  keyed by canonical option path. The mapping's value type is
  ``bool | int | str | list[Any] | dict[str, Any]`` — narrower than
  ``Any`` because the registry constrains it to these shapes, but not
  Pydantic-validated per-key (a future C-step could extend this).
* ``frontend.api_target.type`` / ``frontend.api_target.url`` live on
  the FrontendGenerate / FrontendExternal sub-models — they're
  frontend-scoped options that genuinely belong on the frontend
  discriminator's fields.

The model is **read-only after construction** (``frozen=True``) — the
legacy dict permits in-place mutation, but every consumer the audit
turned up reads only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# -----------------------------------------------------------------------------
# Backend layer
# -----------------------------------------------------------------------------


class BackendGenerate(BaseModel):
    """``backend.mode="generate"`` — forge scaffolds backend services.

    The actual backend list (languages, ports, features) lives on
    ``ProjectConfig.backends`` and isn't duplicated here; this
    sub-model only carries the **mode-scoped** state. The discriminator
    + cross-layer rules (e.g. "empty backends + mode=generate is an
    empty project") stay on ``ProjectConfig.validate``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["generate"] = "generate"


class BackendNone(BaseModel):
    """``backend.mode="none"`` — frontend / infra only, no ``services/``.

    Pairs with ``FrontendExternal`` (the frontend points at an
    externally-hosted API) in the common deployment shape.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["none"] = "none"


BackendConfigT = Annotated[
    BackendGenerate | BackendNone,
    Field(discriminator="mode"),
]


# -----------------------------------------------------------------------------
# Frontend layer
# -----------------------------------------------------------------------------


class FrontendGenerate(BaseModel):
    """``frontend.mode="generate"`` — render the per-framework template.

    Carries the frontend-scoped api-target fields. ``api_target_type``
    distinguishes a local Docker-internal upstream (Vite proxy →
    backend service) from an external URL. ``api_target_url`` is
    consumed even in ``local`` mode for the rare case where the user
    wants Vite to proxy to a non-local host.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["generate"] = "generate"
    api_target_type: Literal["local", "external"] = "local"
    api_target_url: str = ""


class FrontendExternal(BaseModel):
    """``frontend.mode="external"`` — point the generated app at a deployed frontend.

    Reserved for future work where forge renders a thin wrapper that
    proxies to an externally-hosted frontend rather than a generated
    one. The pre-existing ``api_target_url`` field still carries the
    deployed backend URL.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["external"] = "external"
    api_target_type: Literal["local", "external"] = "external"
    api_target_url: str = ""


class FrontendNone(BaseModel):
    """``frontend.mode="none"`` — backend / infra only, no frontend app."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["none"] = "none"


FrontendConfigT = Annotated[
    FrontendGenerate | FrontendExternal | FrontendNone,
    Field(discriminator="mode"),
]


# -----------------------------------------------------------------------------
# Database layer
# -----------------------------------------------------------------------------


class DatabaseGenerate(BaseModel):
    """``database.mode="generate"`` — provision Postgres + Alembic + SQLAlchemy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["generate"] = "generate"
    engine: Literal["postgres"] = "postgres"


class DatabaseNone(BaseModel):
    """``database.mode="none"`` — stateless service / external DB.

    Cross-layer: DB-backed options (``conversation.persistence`` etc.)
    are rejected by ``ProjectConfig._validate_database_mode`` when this
    mode is selected. The check stays on the dataclass so the existing
    actionable error messages keep working.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["none"] = "none"


DatabaseConfigT = Annotated[
    DatabaseGenerate | DatabaseNone,
    Field(discriminator="mode"),
]


# -----------------------------------------------------------------------------
# Agent layer (Theme 2A)
# -----------------------------------------------------------------------------


class AgentNone(BaseModel):
    """``agent.mode="none"`` — no agent stack (default)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["none"] = "none"


class AgentLlmOnly(BaseModel):
    """``agent.mode="llm_only"`` — LlmProviderPort + chat-history persistence."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["llm_only"] = "llm_only"


class AgentToolCalling(BaseModel):
    """``agent.mode="tool_calling"`` — full agent loop + MCP scaffolds."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["tool_calling"] = "tool_calling"


class AgentMultiAgent(BaseModel):
    """``agent.mode="multi_agent"`` — placeholder for v2 agent-to-agent routing.

    Accepted at the typed-model level so users can declare intent in
    ``forge.toml`` today, but ``ProjectConfig._validate_agent_mode``
    raises NOT-YET-IMPLEMENTED before generation runs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["multi_agent"] = "multi_agent"


AgentConfigT = Annotated[
    AgentNone | AgentLlmOnly | AgentToolCalling | AgentMultiAgent,
    Field(discriminator="mode"),
]


# -----------------------------------------------------------------------------
# Root model
# -----------------------------------------------------------------------------


# Aliases that ``from_legacy_options`` rewrites onto canonical paths.
#
# Initiative #7 — the registry's ``OPTION_ALIAS_INDEX`` is the single
# source of truth. Pre-#7 this dict duplicated the index, and the two
# could drift silently. The lookup runs lazily (inside
# ``from_legacy_options``) so importing ``forge.config.typed_config``
# still doesn't trigger ``forge.options``'s registration side effects —
# pydantic-introspection tools that want the model shape can keep
# importing this module standalone.
def _legacy_aliases() -> dict[str, str]:
    """Return the registry's alias → canonical mapping (lazy import).

    Callers (``from_legacy_options``) only invoke this when they actually
    need to rewrite, so the registry side effects stay deferred until
    options actually get processed.
    """
    from forge.options import OPTION_ALIAS_INDEX  # noqa: PLC0415

    return OPTION_ALIAS_INDEX


# Canonical paths consumed by the layer sub-models. ``from_legacy_options``
# routes these into the sub-models and leaves everything else on
# ``TypedConfig.other``.
_LAYER_PATHS: frozenset[str] = frozenset(
    {
        "backend.mode",
        "frontend.mode",
        "frontend.api_target.type",
        "frontend.api_target.url",
        "database.mode",
        "database.engine",
        "agent.mode",
    }
)


class TypedConfig(BaseModel):
    """Typed orchestration config — the future ``ProjectConfig.options`` shape.

    Four layer-mode discriminated unions + a typed bag for everything
    else. The bag's value type is the union of leaf shapes the registry
    can produce (``bool | int | str | list | dict``); a future
    C-extension could replace the bag with one field per registered
    option, but that's outside Theme 5's scope.

    Constructed via :func:`from_legacy_options` — direct construction
    works but skips the alias-rewrite + sub-model routing the converter
    performs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: BackendConfigT = Field(default_factory=lambda: BackendGenerate())
    frontend: FrontendConfigT = Field(default_factory=lambda: FrontendGenerate())
    database: DatabaseConfigT = Field(default_factory=lambda: DatabaseGenerate())
    agent: AgentConfigT = Field(default_factory=lambda: AgentNone())

    # Non-layer options. Keys are canonical Option paths (post-alias-
    # resolution). Values are whatever the registry stores — see the
    # module docstring for the narrowed-Any rationale.
    other: dict[str, Any] = Field(default_factory=dict)


# -----------------------------------------------------------------------------
# Conversion — legacy dict ↔ typed model
# -----------------------------------------------------------------------------


def from_legacy_options(options: dict[str, Any]) -> TypedConfig:
    """Convert a ``ProjectConfig.options`` dict into a :class:`TypedConfig`.

    Steps:

    1. Rewrite known deprecated aliases (``frontend.api_target_url`` →
       ``frontend.api_target.url``) so the sub-model fields see the
       canonical path.
    2. Pull out the layer-mode paths into per-layer sub-model kwargs.
    3. Leave every other key on ``TypedConfig.other``.
    4. Hand the partial dict to :class:`TypedConfig` and let Pydantic
       validate (unknown mode values, wrong types, etc.).

    Failures raise :class:`pydantic.ValidationError` — that's the win:
    the legacy dict would silently shrug a typo like
    ``"backend.mode": "geneate"`` into a ``str`` that downstream
    string-compares against ``"generate"``. The typed model fails
    loudly at conversion time with a useful path.
    """
    aliases = _legacy_aliases()
    canonical: dict[str, Any] = {}
    for raw_path, value in options.items():
        path = aliases.get(raw_path, raw_path)
        canonical[path] = value

    backend_kwargs: dict[str, Any] = {}
    if "backend.mode" in canonical:
        backend_kwargs["mode"] = canonical["backend.mode"]

    frontend_kwargs: dict[str, Any] = {}
    if "frontend.mode" in canonical:
        frontend_kwargs["mode"] = canonical["frontend.mode"]
    # ``api_target_*`` live only on the generate / external variants;
    # ``FrontendNone`` forbids them. The option registry stamps blanket
    # ``frontend.api_target.*`` defaults into forge.toml regardless of
    # mode (#260), so forwarding them for ``mode=none`` would trip
    # ``FrontendNone``'s ``extra="forbid"``. Gate on the effective mode —
    # a value supplied without a mode still implies generate (preserving
    # ``test_frontend_url_alone_implies_generate_mode``). Mirrors the
    # mode-aware asymmetry ``to_legacy_options`` already has.
    if canonical.get("frontend.mode", "generate") != "none":
        if "frontend.api_target.type" in canonical:
            frontend_kwargs["api_target_type"] = canonical["frontend.api_target.type"]
        if "frontend.api_target.url" in canonical:
            frontend_kwargs["api_target_url"] = canonical["frontend.api_target.url"]

    database_kwargs: dict[str, Any] = {}
    if "database.mode" in canonical:
        database_kwargs["mode"] = canonical["database.mode"]
    # ``engine`` exists only on ``DatabaseGenerate``; ``DatabaseNone``
    # forbids it. Same blanket-default leak as the frontend above (#260):
    # gate ``engine`` on the effective mode so a ``database.mode=none``
    # manifest's stamped ``database.engine=postgres`` is dropped instead
    # of crashing ``forge update``. Engine without a mode keeps generate
    # (preserves ``test_database_engine_alone_implies_generate_mode``).
    if "database.engine" in canonical and canonical.get("database.mode", "generate") == "generate":
        database_kwargs["engine"] = canonical["database.engine"]

    agent_kwargs: dict[str, Any] = {}
    if "agent.mode" in canonical:
        agent_kwargs["mode"] = canonical["agent.mode"]

    other = {k: v for k, v in canonical.items() if k not in _LAYER_PATHS}

    root_kwargs: dict[str, Any] = {"other": other}
    if backend_kwargs:
        root_kwargs["backend"] = backend_kwargs
    if frontend_kwargs:
        # ``api_target_type`` / ``api_target_url`` only make sense on
        # the generate / external sub-models. If the user supplied them
        # without an explicit ``mode``, default to ``generate``.
        frontend_kwargs.setdefault("mode", "generate")
        root_kwargs["frontend"] = frontend_kwargs
    if database_kwargs:
        database_kwargs.setdefault("mode", "generate")
        root_kwargs["database"] = database_kwargs
    if agent_kwargs:
        root_kwargs["agent"] = agent_kwargs

    return TypedConfig(**root_kwargs)


def to_legacy_options(typed: TypedConfig) -> dict[str, Any]:
    """Inverse of :func:`from_legacy_options`.

    Reconstructs a ``dict[str, Any]`` that round-trips through the
    converter back to an equal :class:`TypedConfig`. Used by C3 once
    ``ProjectConfig.options`` becomes a derived property — existing
    callers reading ``config.options["backend.mode"]`` keep working.

    Only emits keys that diverge from the registered defaults? **No** —
    emit every layer-mode path the typed model owns, because callers
    rely on ``options.get("backend.mode", "generate")`` returning the
    default when unset, and we don't want to introduce a subtle
    behavior change. The dict represents the **resolved** state of the
    typed model.

    Non-layer values pass through ``other`` unchanged.
    """
    out: dict[str, Any] = dict(typed.other)

    # Backend
    out["backend.mode"] = typed.backend.mode

    # Frontend — always emit ``frontend.mode``; emit api_target fields
    # only when the sub-model carries them (the ``none`` variant
    # doesn't). This matches the pre-C3 behaviour where the user-set
    # dict only contained keys the user supplied.
    out["frontend.mode"] = typed.frontend.mode
    if isinstance(typed.frontend, (FrontendGenerate, FrontendExternal)):
        out["frontend.api_target.type"] = typed.frontend.api_target_type
        out["frontend.api_target.url"] = typed.frontend.api_target_url

    # Database
    out["database.mode"] = typed.database.mode
    if isinstance(typed.database, DatabaseGenerate):
        out["database.engine"] = typed.database.engine

    # Agent
    out["agent.mode"] = typed.agent.mode

    return out


__all__ = [
    "AgentConfigT",
    "AgentLlmOnly",
    "AgentMultiAgent",
    "AgentNone",
    "AgentToolCalling",
    "BackendConfigT",
    "BackendGenerate",
    "BackendNone",
    "DatabaseConfigT",
    "DatabaseGenerate",
    "DatabaseNone",
    "FrontendConfigT",
    "FrontendExternal",
    "FrontendGenerate",
    "FrontendNone",
    "TypedConfig",
    "ValidationError",
    "from_legacy_options",
    "to_legacy_options",
]
