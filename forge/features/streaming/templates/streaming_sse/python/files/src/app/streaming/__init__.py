"""Service-local SSE streamer wiring.

Re-exports the :class:`weld.streaming.CloudEventStreamer` factory and
the default :class:`StreamConfig` so endpoints stay declarative.
"""

from __future__ import annotations

from app.streaming.streamer import build_streamer, default_stream_config

__all__ = ["build_streamer", "default_stream_config"]
