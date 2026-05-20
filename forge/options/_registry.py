"""Option types + the canonical registry singleton.

The user-facing config surface lives here: every knob forge exposes is
an :class:`Option` with a dotted ``path``, a ``type``, a default, and a
realisation map (``enables``) that ties chosen values to template
fragments. Options are *what users pick*; fragments
(``forge/fragments.py``) are the implementation detail.

Design reference: NixOS module options + Terraform provider schemas.
Dotted paths, typed leaves, JSON-Schema-friendly.

This module defines the schema; the per-namespace modules under
``forge/options/`` register the actual options at import time. The
package's ``__init__.py`` triggers those imports so any
``from forge.options import OPTION_REGISTRY`` reads a fully-populated
registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from forge.config._backend import BackendLanguage
    from forge.config._frontend import FrontendFramework

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

    BOOL / ENUM / STR / INT / LIST are leaves. OBJECT is a nested dict
    whose shape is optionally declared via ``Option.object_schema``
    (Phase C). Options of type OBJECT must set ``stability="experimental"``
    until the nested-shape contract stabilises.
    """

    BOOL = "bool"
    ENUM = "enum"
    STR = "str"
    INT = "int"
    LIST = "list"
    OBJECT = "object"


@dataclass(frozen=True)
class ObjectFieldSpec:
    """Describes one key of an OBJECT-typed Option's value (Phase C).

    The shape is a stripped-down Option: ``type`` + (for ENUM)
    ``options`` + a ``required`` flag. ``default`` is captured so that
    validators can apply per-key defaults when a user omits the key,
    mirroring the top-level Option behaviour.

    Declared on ``Option.object_schema`` as ``dict[str, ObjectFieldSpec]``.
    Omitting ``object_schema`` keeps the pre-C behaviour — any dict
    passes outer-shape validation.
    """

    type: OptionType
    required: bool = True
    options: tuple[Any, ...] = ()
    default: Any = None

    def __post_init__(self) -> None:
        if self.type is OptionType.OBJECT:
            raise ValueError(
                "ObjectFieldSpec.type=OBJECT is not supported — nested "
                "OBJECT-of-OBJECT requires a separate registration. "
                "Use the flat key per nesting level instead."
            )
        if self.type is OptionType.ENUM and not self.options:
            raise ValueError(
                "ObjectFieldSpec.type=ENUM requires a non-empty "
                "``options`` tuple listing the allowed values."
            )
        if self.type is not OptionType.ENUM and self.options:
            raise ValueError(
                f"ObjectFieldSpec.type={self.type.value}: `options` is only valid for ENUM fields."
            )


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
    # Phase C — OBJECT nested-field shape. Empty / None means "any dict
    # passes outer-shape validation". Declared as a mapping because the
    # nested schema is stable at registration time (flat keys, no
    # recursion into further OBJECT types).
    object_schema: dict[str, ObjectFieldSpec] | None = None

    # Initiative #7 — compatibility metadata. Replaces the
    # feature-name-dispatching ``ProjectConfig.validate()`` block that
    # used to hard-code "if rag/conversation/events… then check
    # database.mode" rules. The resolver now walks every enabled
    # Option's metadata generically; adding a new feature only requires
    # declaring its constraints next to its other Option fields.
    #
    # ``requires_database`` — when the option is "enabled" (BOOL=True
    # or ENUM≠the false-y value) the resolved fragment plan needs a
    # real database, so ``database.mode != "none"``. Default False so
    # most options stay opt-in.
    requires_database: bool = False
    # ``requires_backend`` — option only makes sense when at least one
    # backend is being generated (``backend.mode != "none"``). Defaults
    # True because every option in the registry today targets a backend
    # service; frontend-only Options must opt out explicitly.
    requires_backend: bool = True
    # ``allowed_backends`` — None means "any registered backend
    # language" (built-in + plugin). Non-None enumerates the supported
    # built-in BackendLanguage values explicitly; the resolver rejects
    # the option when none of the project's backends match.
    allowed_backends: tuple[BackendLanguage, ...] | None = None
    # ``allowed_frontends`` — same semantics for frontends. Only
    # meaningful when the option targets a frontend feature (rare —
    # most registry options target backends).
    allowed_frontends: tuple[FrontendFramework, ...] | None = None
    # ``incompatible_with`` — other canonical option paths that
    # mutual-exclude this one when both are enabled. Mirrors fragment
    # ``conflicts_with`` but at the option layer so the error message
    # can name the user-visible option paths instead of the internal
    # fragment names.
    incompatible_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_path(self.path)
        self._validate_default_matches_type()
        self._validate_options_shape()
        self._validate_enables_shape()
        self._validate_constraints()
        self._validate_aliases()
        self._validate_compat_metadata()

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
        if t is OptionType.OBJECT:
            if not isinstance(d, dict):
                raise ValueError(
                    f"Option {self.path}: OBJECT default must be dict, got {type(d).__name__}"
                )
            if self.stability != "experimental":
                raise ValueError(
                    f"Option {self.path}: OBJECT options must declare "
                    'stability="experimental" — the nested-shape contract '
                    "isn't stable across forge versions yet."
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
                raise ValueError(f"Option {self.path}: alias {alias!r} equals the canonical path")
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError(
                f"Option {self.path}: duplicate entries in aliases {list(self.aliases)}"
            )
        if self.deprecated_since is not None and not self.aliases:
            raise ValueError(f"Option {self.path}: deprecated_since set but no aliases declared")

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

    def _validate_compat_metadata(self) -> None:
        """Initiative #7 — structural checks on compatibility metadata.

        Cross-option checks (``incompatible_with`` targets exist,
        layer modes aren't self-referential) run at resolver time —
        they depend on registry state that doesn't exist yet at
        Option construction. Here we just ensure the per-Option
        shapes are sane.
        """
        if self.allowed_backends is not None and not self.allowed_backends:
            raise ValueError(
                f"Option {self.path}: allowed_backends must be None (any) "
                "or a non-empty tuple — empty tuple means 'no backend can "
                "use this option', which is nonsensical."
            )
        if self.allowed_frontends is not None and not self.allowed_frontends:
            raise ValueError(
                f"Option {self.path}: allowed_frontends must be None (any) "
                "or a non-empty tuple."
            )
        for other in self.incompatible_with:
            _validate_path(other)
            if other == self.path:
                raise ValueError(
                    f"Option {self.path}: incompatible_with includes its "
                    f"own path {other!r} — an option can't conflict with "
                    "itself."
                )
        if len(set(self.incompatible_with)) != len(self.incompatible_with):
            raise ValueError(
                f"Option {self.path}: duplicate entries in incompatible_with "
                f"{list(self.incompatible_with)}"
            )

    # -- convenience ---------------------------------------------------------

    @property
    def namespace(self) -> str:
        """Top-level segment of the path (e.g. ``rag.backend`` → ``rag``)."""
        return self.path.split(".", 1)[0]

    def is_active_value(self, value: Any) -> bool:
        """True when ``value`` represents the option being "turned on".

        Used by the Initiative #7 compatibility walker on
        ``ProjectConfig.validate()``: a BOOL option is active when
        ``True``; an ENUM option is active when its value resolves to
        at least one fragment (i.e. non-empty ``enables`` entry).
        STR / INT / LIST options have no on/off concept — the walker
        treats them as always inactive so compatibility metadata on
        those types is a no-op until callers explicitly opt in.

        The point of this rule is to mirror the pre-Initiative #7
        behaviour: ``rag.backend="none"`` did *not* trigger the old
        hard-coded DB compatibility check, but ``rag.backend="qdrant"``
        did. Both have the same Option object — the value is what
        matters.
        """
        if self.type is OptionType.BOOL:
            return value is True
        if self.type is OptionType.ENUM:
            return bool(self.enables.get(value))
        # STR / INT / LIST / OBJECT — see the docstring; opt out by default.
        return False

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
        if t is OptionType.OBJECT:
            if not isinstance(value, dict):
                raise ValueError(f"Option {self.path}: expected dict, got {type(value).__name__}")
            self._validate_object_shape(value)

    def _validate_object_shape(self, value: dict[str, Any]) -> None:
        """Phase C recursive validation for OBJECT options.

        When ``object_schema`` is declared, every declared field is
        checked against its spec: missing required keys raise, unknown
        keys raise, wrong-typed values raise, ENUM values outside the
        spec's option list raise. When ``object_schema`` is absent the
        value passes the outer-dict check and skips per-key validation —
        matching pre-C behaviour for any OBJECT option that doesn't
        opt in.
        """
        if not self.object_schema:
            return
        allowed = set(self.object_schema)
        supplied = set(value)
        for unknown in supplied - allowed:
            raise ValueError(
                f"Option {self.path}: unknown OBJECT key {unknown!r}. Allowed: {sorted(allowed)}"
            )
        for key, spec in self.object_schema.items():
            if key not in value:
                if spec.required:
                    raise ValueError(f"Option {self.path}: required OBJECT key {key!r} is missing")
                continue
            v = value[key]
            t = spec.type
            if t is OptionType.BOOL and not isinstance(v, bool):
                raise ValueError(f"Option {self.path}.{key}: expected bool, got {type(v).__name__}")
            elif t is OptionType.INT and (not isinstance(v, int) or isinstance(v, bool)):
                raise ValueError(f"Option {self.path}.{key}: expected int, got {type(v).__name__}")
            elif t is OptionType.STR and not isinstance(v, str):
                raise ValueError(f"Option {self.path}.{key}: expected str, got {type(v).__name__}")
            elif t is OptionType.LIST and not isinstance(v, (list, tuple)):
                raise ValueError(f"Option {self.path}.{key}: expected list, got {type(v).__name__}")
            elif t is OptionType.ENUM and v not in spec.options:
                raise ValueError(
                    f"Option {self.path}.{key}: invalid value {v!r}; allowed: {list(spec.options)}"
                )


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
