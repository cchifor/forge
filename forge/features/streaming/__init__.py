"""``streaming.*`` — Server-Sent Events fanout of CloudEvents via weld-streaming.

Wraps :class:`weld.streaming.CloudEventStreamer` so a service exposes a
browser-bound ``/stream`` endpoint with subscription + filter + replay +
heartbeats in one declaration. Depends on ``events_core`` because the
streamer subscribes to a :class:`weld.events.EventBus` instance.

Python-only fragment — `sse-starlette` ships under that name only and
the weld-streaming SDK isn't ported elsewhere.
"""

from __future__ import annotations

from forge.features.streaming import (  # noqa: F401, E402
    fragments,
    options,
)
