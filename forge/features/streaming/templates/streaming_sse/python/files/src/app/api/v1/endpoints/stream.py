"""Browser-bound CloudEvent stream.

GET /api/v1/stream — ``text/event-stream`` of CloudEvents. Browser
clients connect with an ``EventSource``; ``Last-Event-ID`` triggers
replay from the streamer's history.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from weld.streaming import CloudEventStreamer, SubscriberCtx

from app.streaming import default_stream_config

router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream(
    request: Request,
    streamer: CloudEventStreamer = Depends(),
):
    config = default_stream_config(request.app.state.settings)
    ctx = SubscriberCtx(
        last_event_id=request.headers.get("last-event-id"),
        client_ip=request.client.host if request.client else None,
    )
    return streamer.stream(request, config, ctx)
