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
            summary="SSE endpoint that fans CloudEvents to browser subscribers (weld-streaming).",
            description="""\
Adds ``/api/v1/stream`` backed by :class:`weld.streaming.CloudEventStreamer`.
Browsers connect with an ``EventSource``; the streamer manages
subscription, filter, replay (``Last-Event-ID`` handshake) and
heartbeats. Requires ``events.bus ≠ none`` because the streamer pulls
events off the configured :class:`weld.events.EventBus`.

BACKENDS: python
DEPENDENCY: weld-streaming, sse-starlette
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
