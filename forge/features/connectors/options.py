"""``connectors.*`` — pluggable read/write adapter options."""

from __future__ import annotations

from forge.api import ForgeAPI
from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
)


def register_all(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="connectors.enabled",
            type=OptionType.BOOL,
            default=False,
            summary="Pluggable read/write data-plane adapters (vendored).",
            description="""\
Adds a service-local ``app.connectors.ConnectorRegistry`` (vendored,
self-contained) wired into Dishka DI so handlers can look up adapters by
name and type. Builtins are selectable via ``connectors.backends``.

BACKENDS: python
DEPENDENCY: none (vendored; uses pydantic + httpx + sqlalchemy from the
base; boto3 / asyncpg optional for the s3 / postgres backends)""",
            category=FeatureCategory.KNOWLEDGE,
            enables={True: ("connectors_registry",)},
            # The vendored framework imports sqlalchemy from the base and
            # connectors_registry injects into ioc/infra.py — both removed by the
            # database.mode=none stripper, so generation would otherwise crash on
            # the missing FORGE:IOC_INFRA anchors. Reject the stateless combo up
            # front with the standard friendly message instead. (audit #9)
            requires_database=True,
        )
    )

    api.add_option(
        Option(
            path="connectors.backends",
            type=OptionType.LIST,
            default=[],
            summary="Built-in connector backends to enable — subset of {http,fs,sql,s3}.",
            description="""\
Each listed backend is pre-registered in the service's
:class:`ConnectorRegistry`. ``s3`` additionally needs ``boto3`` and
``sql`` against Postgres needs ``asyncpg`` (both optional, import-guarded).
Empty list keeps the registry callable but empty — handlers then register
their own adapters at startup.

BACKENDS: python
ALLOWED: http, fs, sql, s3""",
            category=FeatureCategory.KNOWLEDGE,
        )
    )
