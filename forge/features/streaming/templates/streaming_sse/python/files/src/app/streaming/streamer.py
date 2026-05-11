"""Build the service's :class:`weld.streaming.CloudEventStreamer`.

The streamer is app-scoped (one per service) and reads off the same
:class:`weld.events.EventBus` instance the rest of the app publishes
to. Filters and replay are configured per request via ``StreamConfig``
— the default below is "deliver everything, no replay" so endpoints
override it when they need topic filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weld.streaming import CloudEventStreamer, StreamConfig

if TYPE_CHECKING:
    from app.core.config.domain import Settings
    from weld.events import EventBus


def default_stream_config(settings: Settings) -> StreamConfig:
    return StreamConfig(
        heartbeat_s=settings.streaming.heartbeat_s,
        queue_max=settings.streaming.queue_max,
    )


def build_streamer(bus: EventBus, settings: Settings) -> CloudEventStreamer:
    return CloudEventStreamer(bus=bus, default_config=default_stream_config(settings))
