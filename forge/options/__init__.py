"""User-facing option registry.

P1.1 (1.1.0-alpha.2) — split out of the 1581-line ``forge/options.py``
monolith. The package layout maps one module per dotted-path namespace:

* ``_registry`` — :class:`Option`, :class:`OptionType`,
  :class:`FeatureCategory`, ``register_option``, ``OPTION_REGISTRY``,
  ``OPTION_ALIAS_INDEX``, helpers.
* ``_schema`` — JSON Schema 2020-12 emitter.
* ``middleware`` — ``middleware.*`` (rate limit, correlation, security
  headers, PII redaction, response cache).
* ``observability`` — ``observability.*`` (tracing, health, OTel).
* ``async_work`` — ``async.*``, ``queue.*``.
* ``conversation`` — ``conversation.*``.
* ``agent`` — ``agent.*`` and ``llm.*`` (streaming, tools, llm loop,
  provider, layer discriminator).
* ``chat`` — ``chat.*``.
* ``rag`` — ``rag.*``.
* ``platform_ops`` — ``platform.*``, ``object_store.*``, ``security.*``.
* ``reliability`` — ``reliability.*``.
* ``layers`` — ``backend.*``, ``frontend.*``, ``database.*``
  (discriminated-union mode options).

Importing this package triggers every per-namespace module's
``register_option`` calls, so ``OPTION_REGISTRY`` is fully populated by
the time any caller does ``from forge.options import OPTION_REGISTRY``.
The public surface re-exports the names the rest of the codebase (and
plugin authors) rely on; the underscored modules are implementation
detail.
"""

from __future__ import annotations

# Trigger registrations. Order does not matter — register_option is
# idempotent over collisions, and capability_resolver validates the
# enables → fragment graph after every plugin has had its turn.
from forge.options import (  # noqa: F401, E402
    agent,
    async_work,
    chat,
    conversation,
    layers,
    middleware,
    observability,
    platform_ops,
    rag,
    reliability,
)
from forge.options._registry import (
    CATEGORY_DISPLAY,
    CATEGORY_MISSION,
    CATEGORY_ORDER,
    OPTION_ALIAS_INDEX,
    OPTION_REGISTRY,
    FeatureCategory,
    ObjectFieldSpec,
    Option,
    OptionType,
    Stability,
    get_option,
    options_by_namespace,
    ordered_options,
    register_option,
    resolve_alias,
)
from forge.options._schema import to_json_schema

__all__ = [
    # Categories
    "CATEGORY_DISPLAY",
    "CATEGORY_MISSION",
    "CATEGORY_ORDER",
    "FeatureCategory",
    "Stability",
    # Schema types
    "ObjectFieldSpec",
    "Option",
    "OptionType",
    # Registry + helpers
    "OPTION_ALIAS_INDEX",
    "OPTION_REGISTRY",
    "get_option",
    "options_by_namespace",
    "ordered_options",
    "register_option",
    "resolve_alias",
    # Schema emitter
    "to_json_schema",
]
