"""``airlock.*`` — Airlock sandbox orchestrator client options."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="airlock.client",
        type=OptionType.BOOL,
        default=False,
        summary="Async client for the Airlock sandbox orchestrator (weld-airlock).",
        description="""\
Adds the :class:`weld.airlock.AsyncAirlockClient` to DI plus a startup
hook that closes the underlying httpx session on shutdown. Use for
services that need to spin up ephemeral sandboxes (MCP integrations,
agent-driven workflows, browser automation).

BACKENDS: python
DEPENDENCY: weld-airlock
ENV: AIRLOCK_BASE_URL, AIRLOCK_TOKEN""",
        category=FeatureCategory.PLATFORM,
        enables={True: ("airlock_client",)},
    )
)
