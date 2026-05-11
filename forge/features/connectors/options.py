"""``connectors.*`` — pluggable read/write adapter options."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="connectors.enabled",
        type=OptionType.BOOL,
        default=False,
        summary="Pluggable read/write data-plane adapters (weld-connectors).",
        description="""\
Adds a service-local :class:`weld.connectors.ConnectorRegistry` wired
into Dishka DI so handlers can look up adapters by name and type.
Builtins are selectable via ``connectors.backends`` — each enabled
backend pulls the matching extra.

BACKENDS: python
DEPENDENCY: weld-connectors (+ per-backend extras)""",
        category=FeatureCategory.KNOWLEDGE,
        enables={True: ("connectors_registry",)},
    )
)


register_option(
    Option(
        path="connectors.backends",
        type=OptionType.LIST,
        default=[],
        summary="Built-in connector backends to enable — subset of {http,fs,sql,s3,mcp}.",
        description="""\
Each listed backend pulls ``weld-connectors[<backend>]`` into the
service's pyproject and registers a factory in the
:class:`ConnectorRegistry`. Empty list keeps the registry callable but
empty — handlers then register their own adapters at startup.

BACKENDS: python
ALLOWED: http, fs, sql, s3, mcp""",
        category=FeatureCategory.KNOWLEDGE,
    )
)
