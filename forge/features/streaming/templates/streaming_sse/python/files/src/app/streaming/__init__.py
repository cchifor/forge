"""Service-local SSE streamer wiring (vendored, weld-free).

Re-exports the :class:`CloudEventStreamer` factory, the default
:class:`StreamConfig` helper, and the public streaming types so
endpoints stay declarative::

    from app.streaming import CloudEventStreamer, SubscriberCtx, default_stream_config
"""

from __future__ import annotations

from app.streaming.streamer import (
    CloudEventStreamer,
    build_streamer,
    default_stream_config,
)
from app.streaming.types import (
    StreamConfig,
    StreamFrame,
    SubscriberCtx,
)

__all__ = [
    "CloudEventStreamer",
    "StreamConfig",
    "StreamFrame",
    "SubscriberCtx",
    "build_streamer",
    "default_stream_config",
]
