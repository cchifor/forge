"""``streaming.*`` — SSE fanout options for CloudEvents."""

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
            path="streaming.sse",
            type=OptionType.BOOL,
            default=False,
            summary="SSE endpoint that fans CloudEvents to browser subscribers (vendored).",
            description="""\
Adds ``/api/v1/stream`` backed by ``app.streaming.CloudEventStreamer``
(vendored, self-contained). Browsers connect with an ``EventSource``;
the streamer manages subscription, filter, replay (``Last-Event-ID``
handshake) and heartbeats. Requires ``events.bus ≠ none`` because the
streamer pulls events off the configured ``app.events.EventBus``.

BACKENDS: python
DEPENDENCY: sse-starlette (vendored streamer; bus is vendored too)
ENV: STREAMING_HEARTBEAT_S, STREAMING_QUEUE_MAX""",
            category=FeatureCategory.ASYNC_WORK,
            stability="beta",
            # Initiative #7 — transitively requires the event bus, which
            # requires the DB. Surfacing the constraint here too keeps the
            # diagnostic explicit when the user enables streaming.sse alone.
            requires_database=True,
            enables={True: ("streaming_sse",)},
        )
    )
