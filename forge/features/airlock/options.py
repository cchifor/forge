"""``airlock.*`` — Airlock sandbox orchestrator client options."""

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
            path="airlock.client",
            type=OptionType.BOOL,
            default=False,
            summary="Async client for the Airlock sandbox orchestrator.",
            description="""\
Adds a vendored, weld-free :class:`app.airlock.AsyncAirlockClient` to DI
plus a startup hook that closes the underlying httpx session on
shutdown. Use for services that need to spin up ephemeral sandboxes (MCP
integrations, agent-driven workflows, browser automation).

BACKENDS: python
DEPENDENCY: httpx, pydantic (vendored client — no private SDK)
ENV: AIRLOCK_BASE_URL, AIRLOCK_TOKEN""",
            category=FeatureCategory.PLATFORM,
            # Initiative #7 — airlock client persists sandbox bookkeeping
            # (active sessions, token grants) into the DB.
            requires_database=True,
            enables={True: ("airlock_client",)},
        )
    )
