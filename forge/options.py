"""Unified configuration-option registry — the user-facing config surface.

Replaces the old `FeatureSpec` + `ParameterSpec` split with a single typed
abstraction. Every knob forge exposes is an ``Option`` with a ``path``
(dotted, hierarchical), a ``type`` (bool / enum / str / int / …), a
default, and a realization map (``enables``) that ties chosen values to
template fragments.

Options are the user's surface — CLI flags, YAML keys, forge.toml stamps,
and the emitted JSON Schema all work in terms of Options. Fragments
(``forge/fragments.py``) live one layer below — they're the template
directories in ``forge/templates/_fragments/`` that actually produce code
in the generated project.

Design reference: NixOS module options + Terraform provider schemas.
Dotted paths, typed leaves, JSON-Schema-friendly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Literal

# -----------------------------------------------------------------------------
# Categories — product-level grouping for display
# -----------------------------------------------------------------------------

Stability = Literal["stable", "beta", "experimental"]


class FeatureCategory(Enum):
    """Product-level grouping for the option catalogue.

    Categories describe *what customers are trying to do*. `forge --list`
    prints options in this order; docs/FEATURES.md mirrors the same
    ordering.
    """

    OBSERVABILITY = "observability"
    RELIABILITY = "reliability"
    ASYNC_WORK = "async-work"
    CONVERSATIONAL_AI = "conversational-ai"
    KNOWLEDGE = "knowledge"
    PLATFORM = "platform"


CATEGORY_ORDER: tuple[FeatureCategory, ...] = (
    FeatureCategory.OBSERVABILITY,
    FeatureCategory.RELIABILITY,
    FeatureCategory.ASYNC_WORK,
    FeatureCategory.CONVERSATIONAL_AI,
    FeatureCategory.KNOWLEDGE,
    FeatureCategory.PLATFORM,
)

CATEGORY_DISPLAY: dict[FeatureCategory, str] = {
    FeatureCategory.OBSERVABILITY: "Observability",
    FeatureCategory.RELIABILITY: "Reliability",
    FeatureCategory.ASYNC_WORK: "Async Work",
    FeatureCategory.CONVERSATIONAL_AI: "Conversational AI",
    FeatureCategory.KNOWLEDGE: "Knowledge",
    FeatureCategory.PLATFORM: "Platform",
}

CATEGORY_MISSION: dict[FeatureCategory, str] = {
    FeatureCategory.OBSERVABILITY: "Visibility into the running system — tracing, metrics, health.",
    FeatureCategory.RELIABILITY: "Protection + stability middleware that every production service needs.",
    FeatureCategory.ASYNC_WORK: "Off-thread job processing so request handlers stay fast.",
    FeatureCategory.CONVERSATIONAL_AI: "Chat persistence, tool registry, streaming WebSocket, and an LLM agent loop.",
    FeatureCategory.KNOWLEDGE: "Vector storage and retrieval — the RAG stack with pluggable backends.",
    FeatureCategory.PLATFORM: "Operator-facing tooling: admin UI, outbound webhooks, CLI extensions, AI-agent docs.",
}


# -----------------------------------------------------------------------------
# Option schema
# -----------------------------------------------------------------------------


class OptionType(StrEnum):
    """Primitive type of an Option's value.

    BOOL / ENUM / STR / INT / LIST are leaves. OBJECT is reserved for a
    future nested-submodule shape — Phase 1 registers zero OBJECT options.
    """

    BOOL = "bool"
    ENUM = "enum"
    STR = "str"
    INT = "int"
    LIST = "list"
    OBJECT = "object"


# Dotted path: one-or-more identifiers joined by '.'. Identifiers allow
# letters, digits, underscores. No leading/trailing dot, no empty
# segments. Examples: `rate_limit` (top-level, rare), `rag.backend`,
# `middleware.rate_limit`, `rag.retriever.top_k`.
_PATH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")


def _validate_path(path: str) -> None:
    if not path:
        raise ValueError("Option path cannot be empty")
    if not _PATH_RE.fullmatch(path):
        raise ValueError(
            f"Invalid option path {path!r}: expected dotted identifiers "
            "(letters / digits / underscores), e.g. 'rag.backend' or "
            "'middleware.rate_limit'."
        )


@dataclass(frozen=True)
class Option:
    """One typed configuration knob.

    Every knob forge exposes is an Option. The ``type`` tells readers
    what shape ``default`` and user-supplied values take; ``enables``
    ties each value to the template fragments that realize it.

    Validation runs in ``__post_init__``: path shape, default-vs-type
    compatibility, enum options non-empty, enables keys in options, and
    numeric bounds.
    """

    path: str
    type: OptionType
    default: Any
    summary: str
    description: str
    category: FeatureCategory
    # ENUM: non-empty tuple of allowed values. Other types: ignored.
    options: tuple[Any, ...] = ()
    # value → fragment keys to include in the resolved plan.
    # BOOL: typically {True: (fragment_key,)}; False maps to no fragments.
    # ENUM: one entry per option value (missing value → no fragments).
    # STR / INT / LIST: empty; the value is written into template context,
    # not mapped to fragments.
    enables: dict[Any, tuple[str, ...]] = field(default_factory=dict)
    # User-visible stability tier for this option.
    stability: Stability = "stable"
    # Hide from default `forge --list` view. Rare; most Options are shown.
    hidden: bool = False
    # JSON-Schema-style numeric / string constraints. All optional.
    min: int | None = None
    max: int | None = None
    pattern: str | None = None
    # Epic G (1.1.0-alpha.1) — option aliases + deprecation.
    # ``aliases`` is a tuple of deprecated paths that should resolve to this
    # Option. When a user's forge.toml / YAML / --set uses an alias, the
    # resolver transparently rewrites to the canonical path and emits a
    # deprecation warning pointing at the ``forge migrate-rename-options``
    # codemod. Aliases must pass the same path-shape regex as ``path`` and
    # must not collide with any other registered Option's path or alias.
    aliases: tuple[str, ...] = ()
    # Version the canonical path replaced the first alias. Populates the
    # warning message and the codemod's output so users see when each
    # rename landed.
    deprecated_since: str | None = None

    def __post_init__(self) -> None:
        _validate_path(self.path)
        self._validate_default_matches_type()
        self._validate_options_shape()
        self._validate_enables_shape()
        self._validate_constraints()
        self._validate_aliases()

    # -- validators ----------------------------------------------------------

    def _validate_default_matches_type(self) -> None:
        t = self.type
        d = self.default
        if t is OptionType.BOOL and not isinstance(d, bool):
            raise ValueError(
                f"Option {self.path}: BOOL default must be bool, got {type(d).__name__}"
            )
        if t is OptionType.INT and not (isinstance(d, int) and not isinstance(d, bool)):
            raise ValueError(f"Option {self.path}: INT default must be int, got {type(d).__name__}")
        if t is OptionType.STR and not isinstance(d, str):
            raise ValueError(f"Option {self.path}: STR default must be str, got {type(d).__name__}")
        if t is OptionType.LIST and not isinstance(d, (list, tuple)):
            raise ValueError(
                f"Option {self.path}: LIST default must be list/tuple, got {type(d).__name__}"
            )
        if t is OptionType.ENUM:
            if not self.options:
                raise ValueError(f"Option {self.path}: ENUM requires non-empty options tuple")
            if d not in self.options:
                raise ValueError(
                    f"Option {self.path}: default {d!r} not in options {list(self.options)}"
                )

    def _validate_options_shape(self) -> None:
        # Non-ENUM options should leave the options tuple empty.
        if self.type is not OptionType.ENUM and self.options:
            raise ValueError(
                f"Option {self.path}: `options` is only valid for ENUM; "
                f"{self.type.value} options should leave it empty."
            )

    def _validate_enables_shape(self) -> None:
        if not self.enables:
            return
        if self.type is OptionType.BOOL:
            for key in self.enables:
                if key not in (True, False):
                    raise ValueError(
                        f"Option {self.path}: BOOL enables keys must be True / False, got {key!r}"
                    )
        elif self.type is OptionType.ENUM:
            for key in self.enables:
                if key not in self.options:
                    raise ValueError(
                        f"Option {self.path}: enables key {key!r} not in options {list(self.options)}"
                    )
        else:
            # STR / INT / LIST / OBJECT options map value → template context,
            # not fragments. Surfacing fragments here would confuse readers.
            raise ValueError(
                f"Option {self.path}: `enables` is only meaningful for "
                f"BOOL and ENUM options, not {self.type.value}."
            )

    def _validate_aliases(self) -> None:
        """Epic G — structural checks on declared aliases.

        Cross-option collision checks run in ``register_option`` since they
        depend on registry state that doesn't exist at Option construction.
        """
        for alias in self.aliases:
            _validate_path(alias)
            if alias == self.path:
                raise ValueError(
                    f"Option {self.path}: alias {alias!r} equals the canonical path"
                )
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError(
                f"Option {self.path}: duplicate entries in aliases {list(self.aliases)}"
            )
        if self.deprecated_since is not None and not self.aliases:
            raise ValueError(
                f"Option {self.path}: deprecated_since set but no aliases declared"
            )

    def _validate_constraints(self) -> None:
        if self.min is not None and self.type is not OptionType.INT:
            raise ValueError(f"Option {self.path}: `min` is only valid for INT options")
        if self.max is not None and self.type is not OptionType.INT:
            raise ValueError(f"Option {self.path}: `max` is only valid for INT options")
        if self.pattern is not None and self.type is not OptionType.STR:
            raise ValueError(f"Option {self.path}: `pattern` is only valid for STR options")
        if self.type is OptionType.INT:
            if self.min is not None and self.default < self.min:
                raise ValueError(f"Option {self.path}: default {self.default} < min {self.min}")
            if self.max is not None and self.default > self.max:
                raise ValueError(f"Option {self.path}: default {self.default} > max {self.max}")

    # -- convenience ---------------------------------------------------------

    @property
    def namespace(self) -> str:
        """Top-level segment of the path (e.g. ``rag.backend`` → ``rag``)."""
        return self.path.split(".", 1)[0]

    def validate_value(self, value: Any) -> None:
        """Raise ``ValueError`` if ``value`` isn't admissible for this Option.

        Same type checks as __post_init__ applied to ``value`` instead of
        ``default``. Callers (the YAML loader, the CLI --set parser) use
        this to surface a clean error before the resolver runs.
        """
        t = self.type
        if t is OptionType.BOOL and not isinstance(value, bool):
            raise ValueError(f"Option {self.path}: expected bool, got {type(value).__name__}")
        if t is OptionType.ENUM and value not in self.options:
            raise ValueError(
                f"Option {self.path}: invalid value {value!r}; allowed: {list(self.options)}"
            )
        if t is OptionType.INT:
            if not (isinstance(value, int) and not isinstance(value, bool)):
                raise ValueError(f"Option {self.path}: expected int, got {type(value).__name__}")
            if self.min is not None and value < self.min:
                raise ValueError(f"Option {self.path}: {value} < min {self.min}")
            if self.max is not None and value > self.max:
                raise ValueError(f"Option {self.path}: {value} > max {self.max}")
        if t is OptionType.STR:
            if not isinstance(value, str):
                raise ValueError(f"Option {self.path}: expected str, got {type(value).__name__}")
            if self.pattern is not None and not re.fullmatch(self.pattern, value):
                raise ValueError(
                    f"Option {self.path}: {value!r} does not match pattern {self.pattern}"
                )
        if t is OptionType.LIST and not isinstance(value, (list, tuple)):
            raise ValueError(f"Option {self.path}: expected list, got {type(value).__name__}")


# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------

OPTION_REGISTRY: dict[str, Option] = {}

# Epic G (1.1.0-alpha.1) — alias → canonical path index. Populated by
# ``register_option`` every time an Option declares ``aliases=(...,)``.
# ``capability_resolver._apply_option_defaults`` consults this to rewrite
# user-supplied alias paths before validation. Keeping the index separate
# from OPTION_REGISTRY means the main registry stays keyed by canonical
# paths only — get_option by alias is an explicit opt-in via
# ``resolve_alias``.
OPTION_ALIAS_INDEX: dict[str, str] = {}


def register_option(opt: Option) -> None:
    """Register an Option. Raises on duplicate path or alias collision.

    Fragment-key references in ``opt.enables`` are not validated here —
    fragments may be registered after options. ``capability_resolver``
    validates the full graph once everything has loaded.

    Alias collision checks (Epic G): an alias must not equal any
    existing canonical path or any previously-registered alias. The
    error message names the other Option so operators can find the
    conflict quickly.
    """
    if opt.path in OPTION_REGISTRY:
        raise ValueError(f"Option {opt.path!r} is already registered")
    if opt.path in OPTION_ALIAS_INDEX:
        raise ValueError(
            f"Option {opt.path!r}: path collides with an existing alias "
            f"(rename the alias on {OPTION_ALIAS_INDEX[opt.path]!r})"
        )
    for alias in opt.aliases:
        if alias in OPTION_REGISTRY:
            raise ValueError(
                f"Option {opt.path!r}: alias {alias!r} already registered as "
                f"a canonical Option path"
            )
        if alias in OPTION_ALIAS_INDEX:
            raise ValueError(
                f"Option {opt.path!r}: alias {alias!r} already aliased to "
                f"{OPTION_ALIAS_INDEX[alias]!r}"
            )
    OPTION_REGISTRY[opt.path] = opt
    for alias in opt.aliases:
        OPTION_ALIAS_INDEX[alias] = opt.path


def resolve_alias(path: str) -> str | None:
    """Return the canonical path for an alias, or ``None`` if not aliased.

    Part of Epic G's alias machinery. Called by the resolver before it
    walks the user's option dict so a rename doesn't silently drop the
    user's value to the default.
    """
    return OPTION_ALIAS_INDEX.get(path)


def get_option(path: str) -> Option | None:
    """Lookup by canonical path (exact match, no alias resolution)."""
    return OPTION_REGISTRY.get(path)


def options_by_namespace() -> dict[str, list[Option]]:
    """Group registered options by top-level path segment.

    Useful for display (``forge --list`` namespace sections) and for the
    JSON-Schema emitter. Within a namespace, options are sorted by full
    path for stable output.
    """
    out: dict[str, list[Option]] = {}
    for path in sorted(OPTION_REGISTRY):
        opt = OPTION_REGISTRY[path]
        out.setdefault(opt.namespace, []).append(opt)
    return out


def ordered_options() -> list[Option]:
    """Registered options in (category-order, path) order.

    Matches the display order used by ``forge --list`` so every surface
    that iterates options shares a single deterministic sequence.
    """
    by_cat: dict[FeatureCategory, list[Option]] = {}
    for opt in OPTION_REGISTRY.values():
        by_cat.setdefault(opt.category, []).append(opt)
    out: list[Option] = []
    for cat in CATEGORY_ORDER:
        out.extend(sorted(by_cat.get(cat, []), key=lambda o: o.path))
    # Catch any category that somehow isn't in CATEGORY_ORDER — emit last.
    emitted = set(CATEGORY_ORDER)
    for cat, opts in by_cat.items():
        if cat not in emitted:
            out.extend(sorted(opts, key=lambda o: o.path))
    return out


# -----------------------------------------------------------------------------
# JSON Schema emitter (Draft 2020-12)
# -----------------------------------------------------------------------------


def to_json_schema() -> dict[str, Any]:
    """Return the whole registry as a JSON Schema 2020-12 document.

    Each Option becomes a property on the top-level object. ``title`` /
    ``description`` / ``default`` / ``enum`` / ``minimum`` / ``maximum``
    / ``pattern`` follow the standard schema vocabulary so any
    JSON-Schema library can validate user configs without custom logic.

    ``additionalProperties`` is ``false`` — unknown option paths fail
    validation. Consumers wanting laxer behavior can edit the dumped
    document.
    """
    properties: dict[str, dict[str, Any]] = {}
    for opt in ordered_options():
        prop: dict[str, Any] = {
            "title": opt.path,
            "description": opt.summary or opt.description.splitlines()[0]
            if opt.description
            else "",
            "default": opt.default,
        }
        if opt.type is OptionType.BOOL:
            prop["type"] = "boolean"
        elif opt.type is OptionType.ENUM:
            # JSON-Schema "enum" constrains to the options set; the
            # underlying type is whatever the values are (usually string).
            prop["type"] = _python_to_schema_type(opt.options[0])
            prop["enum"] = list(opt.options)
        elif opt.type is OptionType.INT:
            prop["type"] = "integer"
            if opt.min is not None:
                prop["minimum"] = opt.min
            if opt.max is not None:
                prop["maximum"] = opt.max
        elif opt.type is OptionType.STR:
            prop["type"] = "string"
            if opt.pattern is not None:
                prop["pattern"] = opt.pattern
        elif opt.type is OptionType.LIST:
            prop["type"] = "array"
        elif opt.type is OptionType.OBJECT:
            prop["type"] = "object"
        properties[opt.path] = prop

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "forge options",
        "description": "Typed configuration surface for the forge project generator.",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }


def _python_to_schema_type(value: Any) -> str:
    """Map a Python value's runtime type to a JSON-Schema type literal."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


# -----------------------------------------------------------------------------
# Registered options
# -----------------------------------------------------------------------------
#
# Every user-facing configuration knob lives here. Fragments (the
# template-level implementation detail) live in ``forge/fragments.py`` —
# each Option's ``enables`` map references fragments by name.
#
# Paths are namespaced by product category:
#   middleware.*       — observability-adjacent request middleware
#   observability.*    — tracing, health probes
#   async.*            — background-task queues
#   conversation.*     — chat history storage
#   agent.*            — LLM agent platform
#   chat.*             — chat UX adjuncts (attachments, etc.)
#   rag.*              — knowledge / retrieval
#   platform.*         — operator-facing UIs, CLIs, outbound webhooks
#
# Enum options (rag.backend, rag.embeddings) carry all valid values in
# ``options`` and map each to the fragment set that realises it.
# Boolean options map True → (fragment,) with no False entry.


# --- Middleware -------------------------------------------------------------

register_option(
    Option(
        path="middleware.correlation_id",
        type=OptionType.ENUM,
        default="always-on",
        options=("always-on",),  # degenerate single-value enum
        summary="X-Request-ID ingress + ContextVar propagation.",
        description="""\
Every inbound request is tagged with an X-Request-ID header, the value
is stored in a ContextVar so any async task downstream sees it, and the
same ID is echoed back on the response.

This option is always-on — it has no off value. Index the
``correlation_id`` log field in your aggregator to trace a single
request end-to-end across services.

BACKENDS: python
ENDPOINTS: none — ambient context via service.observability.correlation""",
        category=FeatureCategory.OBSERVABILITY,
        enables={"always-on": ("correlation_id",)},
    )
)


register_option(
    Option(
        path="middleware.rate_limit",
        type=OptionType.BOOL,
        default=True,
        summary="Token-bucket limiter keyed by tenant or IP.",
        description="""\
Token-bucket rate limiter, keyed by tenant when authenticated or by
client IP otherwise. Protects downstream services from hot callers and
smooths burst traffic. Ships three first-class implementations with
matching knobs — Python (in-memory), Node (@fastify/rate-limit), Rust
(Axum tower layer).

BACKENDS: python, node, rust
ENDPOINTS: returns 429 on limit breach; /health and /metrics skipped.
REQUIRES: nothing by default; set REDIS_URL to share state across replicas.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("rate_limit",)},
    )
)


register_option(
    Option(
        path="middleware.security_headers",
        type=OptionType.BOOL,
        default=True,
        summary="CSP + XFO + HSTS + Referrer-Policy + Permissions-Policy.",
        description="""\
Attaches a conservative set of response headers (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, and HSTS
on HTTPS responses) to every request. Turning this off is a deliberate
choice for intentionally-insecure demos.

BACKENDS: python, node, rust
ENDPOINTS: none — middleware decorates every response.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("security_headers",)},
    )
)


register_option(
    Option(
        path="middleware.pii_redaction",
        type=OptionType.BOOL,
        default=True,
        summary="Logging filter that scrubs emails / tokens / API keys.",
        description="""\
A logging.Filter attached at startup that scrubs emails, bearer tokens,
common API-key shapes (sk-*, sk-ant-*, AIza*, hf_*), and
password=/api_key= value pairs from every log record before handlers
run. Helps satisfy GDPR / SOC2 log-hygiene requirements without
per-call-site discipline.

BACKENDS: python
ENDPOINTS: none — applies to logger output globally.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("pii_redaction",)},
    )
)


register_option(
    Option(
        path="middleware.response_cache",
        type=OptionType.BOOL,
        default=False,
        summary="Opt-in HTTP response caching (Redis or in-memory).",
        description="""\
Wires a cache backend at startup so route handlers can decorate
themselves for server-side response caching. Python uses fastapi-cache2
with a Redis backend (falls back to in-memory if RESPONSE_CACHE_URL
isn't set); Node uses @fastify/caching. No blanket behavior change —
handlers opt in per-endpoint.

BACKENDS: python, node
ENDPOINTS: none — decorate existing routes with @cache(expire=N).
REQUIRES: RESPONSE_CACHE_URL pointing at Redis (recommended for prod).""",
        category=FeatureCategory.RELIABILITY,
        stability="beta",
        enables={True: ("response_cache",)},
    )
)


# --- Observability ----------------------------------------------------------

register_option(
    Option(
        path="observability.tracing",
        type=OptionType.BOOL,
        default=False,
        summary="Distributed tracing -- Logfire / OTel SDK / OTLP gRPC.",
        description="""\
Distributed tracing + structured logs wired out of the box. Python uses
Logfire (which exports OTLP under the hood); Node uses @opentelemetry
auto-instrumentations for HTTP / DB / Fastify spans; Rust uses
tracing-opentelemetry + OTLP gRPC. All three honour the same OTel
semantic-convention service name so your tracing backend (Jaeger,
Tempo, Honeycomb, Datadog APM, Logfire) sees one service-map across
languages.

BACKENDS: python, node, rust
REQUIRES: OTEL_EXPORTER_OTLP_ENDPOINT (or LOGFIRE_TOKEN on Python).""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("observability",)},
    )
)


register_option(
    Option(
        path="observability.health",
        type=OptionType.BOOL,
        default=False,
        summary="/health aggregates Postgres + Redis + Keycloak readiness.",
        description="""\
Upgrades the default /health check to a deep readiness probe that
verifies DB connectivity, Redis ping, and Keycloak health endpoint
reachability. Each dependency reports individually so an orchestrator
(Kubernetes readiness gate, load balancer) sees which specific
downstream is down rather than an opaque 503.

BACKENDS: python, node, rust
ENDPOINTS: /health (replaces the shallow default)
REQUIRES: REDIS_URL, KEYCLOAK_HEALTH_URL.""",
        category=FeatureCategory.OBSERVABILITY,
        stability="beta",
        enables={True: ("enhanced_health",)},
    )
)


# --- Async work -------------------------------------------------------------

register_option(
    Option(
        path="async.task_queue",
        type=OptionType.BOOL,
        default=False,
        summary="Redis-backed job queue (Taskiq / BullMQ / Apalis).",
        description="""\
A Redis-backed job queue + example task + worker binary. Define jobs as
regular async functions, enqueue them from request handlers, process
them out-of-process in a dedicated worker container. Ships with Taskiq
(Python), BullMQ + ioredis (Node), and Apalis (Rust) — three different
ecosystems with the same env-var convention (TASKIQ_BROKER_URL).

BACKENDS: python, node, rust
REQUIRES: TASKIQ_BROKER_URL → Redis.""",
        category=FeatureCategory.ASYNC_WORK,
        stability="beta",
        enables={True: ("background_tasks",)},
    )
)


register_option(
    Option(
        path="async.rag_ingest_queue",
        type=OptionType.BOOL,
        default=False,
        summary="Taskiq tasks that move RAG ingest off the request thread.",
        description="""\
Taskiq tasks that move RAG ingestion off the request thread. Enqueue
with ``await ingest_text_task.kiq(...)`` or
``ingest_pdf_bytes_task.kiq(...)`` from any handler — the worker picks
it up and runs chunk + embed + store in the background. The endpoint
returns immediately with a task ID.

BACKENDS: python
REQUIRES: rag.backend ≠ none + async.task_queue = true.""",
        category=FeatureCategory.ASYNC_WORK,
        stability="experimental",
        enables={True: ("rag_sync_tasks",)},
    )
)


# --- Conversation (chat history) --------------------------------------------

register_option(
    Option(
        path="conversation.persistence",
        type=OptionType.BOOL,
        default=False,
        summary="SQLAlchemy Conversation / Message / ToolCall + migration.",
        description="""\
SQLAlchemy models + Pydantic schemas + a repository for Conversation,
Message, and ToolCall rows, plus the Alembic migration that creates
them. Rows are tenant + user scoped. This is the foundation the agent
stream persists history to.

BACKENDS: python
REQUIRES: migration 0002 applied (``alembic upgrade head``).""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="beta",
        enables={True: ("conversation_persistence",)},
    )
)


# --- Agent platform ---------------------------------------------------------

register_option(
    Option(
        path="agent.streaming",
        type=OptionType.BOOL,
        default=False,
        summary="/ws/agent with typed event protocol + runner dispatch.",
        description="""\
A WebSocket endpoint at /api/v1/ws/agent that streams typed AgentEvent
JSON frames (conversation_created, user_prompt, text_delta, tool_call,
tool_result, agent_status, error). Ships with an echo runner and a
runner-dispatch module that prefers ``app.agents.llm_runner`` if
present — enabling ``agent.llm`` swaps in a real LLM loop with zero
endpoint churn.

BACKENDS: python
ENDPOINTS: /api/v1/ws/agent (WebSocket)
REQUIRES: conversation.persistence = true.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="experimental",
        enables={True: ("agent_streaming",)},
    )
)


register_option(
    Option(
        path="agent.tools",
        type=OptionType.BOOL,
        default=False,
        summary="Tool registry + pre-baked `current_datetime`, `web_search`.",
        description="""\
A lightweight Tool base class, a process-wide registry, and two
pre-baked tools (current_datetime, web_search via Tavily). When
rag.backend ≠ none it auto-registers rag_search too. Exposes a
/api/v1/tools list + invoke endpoint so humans can exercise tools
without an LLM loop attached.

BACKENDS: python
ENDPOINTS: /api/v1/tools (GET list, POST invoke)
REQUIRES: TAVILY_API_KEY for the web_search tool (optional).""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="experimental",
        enables={True: ("agent_tools",)},
    )
)


register_option(
    Option(
        path="agent.llm",
        type=OptionType.BOOL,
        default=False,
        summary="pydantic-ai loop -- Anthropic / OpenAI / Google / OpenRouter.",
        description="""\
A pydantic-ai LLM loop that swaps in for the echo runner shipped by
agent.streaming — no endpoint or WebSocket-contract change needed.
Auto-picks the provider from LLM_PROVIDER (anthropic / openai / google
/ openrouter). Every tool registered in the ToolRegistry is bridged
into pydantic-ai automatically.

BACKENDS: python
REQUIRES: one of ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY /
OPENROUTER_API_KEY; agent.streaming = true; agent.tools = true.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="experimental",
        enables={True: ("agent",)},
    )
)


# --- Chat UX ----------------------------------------------------------------

register_option(
    Option(
        path="chat.attachments",
        type=OptionType.BOOL,
        default=False,
        summary="/chat-files multipart + ChatFile model + local storage.",
        description="""\
Multipart upload + download endpoints under /api/v1/chat-files with
local-disk storage, configurable size + MIME allow-list, and a
ChatFile SQLAlchemy model + migration for users who want DB
persistence. The endpoint is storage-only by default (no DB write) so
dropping it in doesn't require Dishka DI changes.

BACKENDS: python
ENDPOINTS: /api/v1/chat-files (upload + download by id)
REQUIRES: conversation.persistence = true; UPLOAD_DIR writable.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="beta",
        enables={True: ("file_upload",)},
    )
)


# --- Knowledge (RAG) --------------------------------------------------------

register_option(
    Option(
        path="rag.backend",
        type=OptionType.ENUM,
        default="none",
        options=(
            "none",
            "pgvector",
            "qdrant",
            "chroma",
            "milvus",
            "weaviate",
            "pinecone",
            "postgresql",
        ),
        summary="Select the vector-store backend for RAG ingest + search.",
        description="""\
Picks which vector store the generated service talks to. ``none`` skips
the RAG stack entirely. ``pgvector`` uses the default Postgres
extension. All other values swap in an alternative backend alongside
the shared chunker + embeddings + PDF-parser modules.

OPTIONS: none | pgvector | qdrant | chroma | milvus | weaviate | pinecone | postgresql""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
        # conversation_persistence is a transitive dep of rag_pipeline;
        # bundling it means a single `rag.backend=<x>` spin is
        # self-contained (the resolver won't error on a missing dep).
        # 1.0.0a2: rag.backend now drives the port+adapter pattern
        # (ADR-002). The vector_store_port fragment is always applied
        # alongside the chosen adapter, so a generated project can swap
        # providers via env config without regeneration. Legacy rag_*
        # fragments are deprecated but still resolvable for
        # pre-1.0.0a2 projects invoking `forge --update`.
        enables={
            "pgvector": ("conversation_persistence", "rag_pipeline", "vector_store_port", "vector_store_postgres"),
            "qdrant": ("conversation_persistence", "rag_pipeline", "vector_store_port", "vector_store_qdrant"),
            "chroma": ("conversation_persistence", "rag_pipeline", "vector_store_port", "vector_store_chroma"),
            "milvus": ("conversation_persistence", "rag_pipeline", "vector_store_port", "vector_store_milvus"),
            "weaviate": ("conversation_persistence", "rag_pipeline", "vector_store_port", "vector_store_weaviate"),
            "pinecone": ("conversation_persistence", "rag_pipeline", "vector_store_port", "vector_store_pinecone"),
            "postgresql": ("conversation_persistence", "rag_pipeline", "vector_store_port", "vector_store_postgres"),
        },
    )
)


register_option(
    Option(
        path="rag.embeddings",
        type=OptionType.ENUM,
        default="openai",
        options=("openai", "voyage"),
        summary="Embeddings provider for RAG ingest + query.",
        description="""\
OpenAI's text-embedding-3-small (1536-dim) is the default. Voyage AI
offers domain-specialized models (voyage-3.5, voyage-code-3,
voyage-finance-2) that typically score higher on retrieval benchmarks
— at the cost of a separate API key and incompatible vector shapes
(rebuild the index after switching).

Only meaningful when ``rag.backend ≠ none``.

OPTIONS: openai | voyage""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
        enables={"voyage": ("rag_embeddings_voyage",)},
    )
)


register_option(
    Option(
        path="rag.reranker",
        type=OptionType.BOOL,
        default=False,
        summary="Cohere rerank (+ local cross-encoder fallback) for sharper top-K.",
        description="""\
Post-retrieval rerank pass. Oversamples candidates from the vector
store and reorders them with a cross-encoder so top-K is sharper than
pure embedding similarity gives you. Cohere is the default provider; a
local sentence-transformers cross-encoder is available as an opt-in
fallback. Degrades to a silent no-op when no provider is configured.

BACKENDS: python
ENDPOINTS: /api/v1/rag/rerank/search
REQUIRES: rag.backend ≠ none; COHERE_API_KEY.""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
        enables={True: ("rag_reranking",)},
    )
)


register_option(
    Option(
        path="rag.top_k",
        type=OptionType.INT,
        default=5,
        min=1,
        max=100,
        summary="Default number of chunks returned per RAG query.",
        description="""\
Number of top-K chunks the RAG retriever returns by default. Only
meaningful when ``rag.backend ≠ none``. Callers can still override
per-query via the top_k parameter on /api/v1/rag/search.

Used as the default for every rag_* endpoint and the `rag_search` agent
tool. Written into .env.example as RAG_TOP_K.""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
    )
)


# --- Platform ---------------------------------------------------------------

register_option(
    Option(
        path="platform.admin",
        type=OptionType.BOOL,
        default=False,
        summary="SQLAdmin UI at /admin -- tenant-scoped ModelViews.",
        description="""\
A browser-facing admin UI mounted at /admin, built on SQLAdmin. It
auto-registers ModelViews for whichever tables the enabled options
have shipped — items, audit_logs, conversations, messages, webhooks
— and skips any model whose Python import fails.

BACKENDS: python
ENDPOINTS: /admin (HTML UI)
REQUIRES: ADMIN_PANEL_MODE=disabled|dev|all (env var); sqladmin +
itsdangerous.""",
        category=FeatureCategory.PLATFORM,
        stability="beta",
        enables={True: ("admin_panel",)},
    )
)


register_option(
    Option(
        path="platform.webhooks",
        type=OptionType.BOOL,
        default=False,
        summary="Outbound registry + HMAC-signed delivery (ts + nonce + body).",
        description="""\
A registry + HMAC-SHA256 signed outbound delivery pipeline. Clients
POST to /api/v1/webhooks to register a target URL; your code calls
``fireEvent`` to deliver a signed JSON payload. Receiver verifies the
same way across all three backends — the signature header format is
identical.

BACKENDS: python, node, rust
ENDPOINTS: /api/v1/webhooks (CRUD + /{id}/test fire)""",
        category=FeatureCategory.PLATFORM,
        stability="beta",
        enables={True: ("webhooks",)},
    )
)


register_option(
    Option(
        path="platform.cli_extensions",
        type=OptionType.BOOL,
        default=False,
        summary="Typer subcommands -- `app info`, `app tools`, `app rag`.",
        description="""\
Extends the generated service's ``app`` typer CLI with operational
subcommands: ``app info show`` (environment dump), ``app tools
list``/``invoke`` (exercise registered agent tools), ``app rag
ingest`` (ingest a local file into the knowledge base). Each subcommand
degrades gracefully — if its prerequisite option isn't enabled, it
prints a hint and exits non-zero.

BACKENDS: python
ENDPOINTS: none — CLI surface only.""",
        category=FeatureCategory.PLATFORM,
        stability="beta",
        enables={True: ("cli_commands",)},
    )
)


register_option(
    Option(
        path="platform.mcp",
        type=OptionType.BOOL,
        default=False,
        summary="Model Context Protocol router + UI scaffolds for tool discovery and approval.",
        description="""\
Scaffolds a backend ``/mcp/tools`` + ``/mcp/invoke`` router (Python,
FastAPI) plus Vue ToolRegistry + ApprovalDialog components. Config
lives at project-root ``mcp.config.json`` (schema at
``forge/templates/_shared/mcp/mcp_config_schema.json``). Real MCP
subprocess spawning and tool-call proxying land in 1.0.0a3 — this alpha
ships the stable endpoints + UI surface so integrators can start
wiring today.

BACKENDS: python
FRONTENDS: vue (svelte + flutter in 1.0.0a3)
DOCS: docs/mcp.md.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        enables={True: ("mcp_server", "mcp_ui")},
    )
)


register_option(
    Option(
        path="platform.agents_md",
        type=OptionType.BOOL,
        default=True,
        summary="Drops AGENTS.md + CLAUDE.md for AI-coding-agent orientation.",
        description="""\
Drops AGENTS.md + CLAUDE.md at the project root so AI coding agents
(Claude Code, Cursor, Copilot workspaces) have a structured
orientation document before they touch generated code. Covers the
option stamp, backend layout, test commands, and the house
conventions so agents ship PRs that match the project's style on the
first try.

BACKENDS: python, node, rust (same content, project-scoped)""",
        category=FeatureCategory.PLATFORM,
        enables={True: ("agents_md",)},
    )
)


# -- Reliability defaults (Phase 4.1, 1.0.0a1) ------------------------------

register_option(
    Option(
        path="queue.backend",
        type=OptionType.ENUM,
        default="none",
        options=("none", "redis", "sqs"),
        summary="Background-work queue — Redis lists or AWS SQS, behind the QueuePort.",
        description="""\
Selects which queue implementation the ``QueuePort`` resolves to.
Redis is the simple-and-cheap default for self-hosted setups; SQS
covers AWS-native deployments with delayed delivery + FIFO.

OPTIONS: none | redis | sqs
BACKENDS: python
DEPENDENCY: redis-py (redis) or aioboto3 (sqs)
ENV: REDIS_URL / AWS_REGION""",
        category=FeatureCategory.ASYNC_WORK,
        enables={
            "redis": ("queue_port", "queue_redis"),
            "sqs": ("queue_port", "queue_sqs"),
        },
    )
)


register_option(
    Option(
        path="object_store.backend",
        type=OptionType.ENUM,
        default="none",
        options=("none", "s3", "local"),
        summary="Blob storage — AWS S3 / S3-compatible / local filesystem, behind ObjectStorePort.",
        description="""\
Selects which object-store implementation backs the ``ObjectStorePort``.
The ``s3`` adapter also handles MinIO / R2 / Wasabi (set S3_ENDPOINT_URL).
The ``local`` adapter writes under a filesystem root — dev / test only.

OPTIONS: none | s3 | local
BACKENDS: python
DEPENDENCY: aioboto3 (s3) | none (local)
ENV: AWS_REGION / S3_ENDPOINT_URL / OBJECT_STORE_ROOT""",
        category=FeatureCategory.PLATFORM,
        enables={
            "s3": ("object_store_port", "object_store_s3"),
            "local": ("object_store_port", "object_store_local"),
        },
    )
)


register_option(
    Option(
        path="llm.provider",
        type=OptionType.ENUM,
        default="none",
        options=("none", "openai", "anthropic", "ollama", "bedrock"),
        summary="LLM provider for the agent loop (OpenAI, Anthropic, Ollama, or AWS Bedrock).",
        description="""\
Selects which LLM provider the generated service talks to via the
``LlmProviderPort`` (see ``docs/architecture-decisions/ADR-002-ports-and-adapters.md``).
The chosen adapter registers with the dependency container; the rest
of the app imports the Protocol. Swap providers in production by
changing one env var — no regeneration.

OPTIONS: none | openai | anthropic | ollama | bedrock
BACKENDS: python
DEPENDENCY: provider-specific SDK (openai / anthropic / ollama / aioboto3)
ENV: provider-specific API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        enables={
            "openai": ("llm_port", "llm_openai"),
            "anthropic": ("llm_port", "llm_anthropic"),
            "ollama": ("llm_port", "llm_ollama"),
            "bedrock": ("llm_port", "llm_bedrock"),
        },
    )
)


register_option(
    Option(
        path="security.csp",
        type=OptionType.BOOL,
        default=True,
        summary="Strict Content-Security-Policy + HSTS + X-Content-Type-Options via nginx.",
        description="""\
Drops ``infra/nginx-csp.conf`` with production-ready strict CSP (no
unsafe-inline, strict-dynamic, nonce-based script tags), HSTS, and
related defence-in-depth headers. ``include infra/nginx-csp.conf;`` from
any nginx server{} block.

BACKENDS: all (project-scoped)
DEV NOTE: relax the ``connect-src`` directive during local development
if your dev server streams from a non-default origin.""",
        category=FeatureCategory.PLATFORM,
        enables={True: ("security_csp",)},
    )
)


register_option(
    Option(
        path="security.sbom",
        type=OptionType.BOOL,
        default=False,
        summary="GitHub Actions workflow emitting a CycloneDX SBOM + pip-audit report.",
        description="""\
Adds ``.github/workflows/sbom.yml`` that generates a CycloneDX SBOM on
every push and runs pip-audit weekly. Artifacts are uploaded so SBOM
attestation and vulnerability disclosure happens as part of normal CI.

BACKENDS: python
DEPENDENCY: none runtime; CI installs cyclonedx-bom + pip-audit.""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("security_sbom",)},
    )
)


register_option(
    Option(
        path="observability.otel",
        type=OptionType.BOOL,
        default=False,
        summary="OpenTelemetry traces + metrics via OTLP exporter (agent.run, tool.call spans).",
        description="""\
Emits ``app/core/otel.py`` wiring FastAPI + HTTPX instrumentations and an
OTLP exporter to whatever ``OTEL_EXPORTER_OTLP_ENDPOINT`` points at.
Spans of interest for agentic workloads: ``agent.run`` (per agent
invocation), ``tool.call`` (per tool invocation). Token / cost counters
from AG-UI RUN_FINISHED are attached as span attributes.

BACKENDS: python
DEPENDENCIES: opentelemetry-api / sdk / exporter-otlp / instrumentation-fastapi / instrumentation-httpx
ENV: OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES.""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("observability_otel",)},
    )
)


register_option(
    Option(
        path="reliability.connection_pool",
        type=OptionType.BOOL,
        default=True,
        summary="Sane SQLAlchemy async pool defaults (size=20, overflow=10, pre_ping, recycle=30m).",
        description="""\
Emits ``app/core/db_pool.py`` with production-ready SQLAlchemy pool
settings and env-var overrides. Without this fragment, generated
projects run on SQLAlchemy's default pool_size=5, which saturates under
moderate burst traffic and produces mysterious 99p tail latency.

BACKENDS: python
TUNABLE VIA ENV: SQLALCHEMY_POOL_SIZE, SQLALCHEMY_MAX_OVERFLOW,
SQLALCHEMY_POOL_PRE_PING, SQLALCHEMY_POOL_RECYCLE.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("reliability_connection_pool",)},
    )
)


register_option(
    Option(
        path="reliability.circuit_breaker",
        type=OptionType.BOOL,
        default=False,
        summary="Circuit breaker for outbound HTTP calls (LLM, vector store, auth).",
        description="""\
Emits ``app/core/circuit_breaker.py`` backed by the purgatory library.
Wraps downstream dependencies so a flaky provider doesn't cascade
failures into every request.

BACKENDS: python
DEPENDENCY: purgatory>=3.0.0
TUNABLE VIA ENV: CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_RESET_TIMEOUT.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("reliability_circuit_breaker",)},
    )
)
