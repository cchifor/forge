"""Browser-bound CloudEvent stream.

GET /api/v1/stream — ``text/event-stream`` of CloudEvents. Browser
clients connect with an ``EventSource``; ``Last-Event-ID`` triggers
replay from a configured replay provider (none by default).
"""

from __future__ import annotations

from app.streaming import CloudEventStreamer, SubscriberCtx, default_stream_config
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request

# DishkaRoute resolves ``FromDishka[...]`` params from the app-scoped
# container. Plain ``Depends()`` would make FastAPI introspect
# ``CloudEventStreamer.__init__`` (bus: EventBusLike) and choke on the
# Protocol as a Pydantic field type — the streamer is a DI singleton, not a
# request body.
router = APIRouter(tags=["stream"], route_class=DishkaRoute)


@router.get("/stream")
async def stream(
    request: Request,
    streamer: FromDishka[CloudEventStreamer],
):
    config = default_stream_config(request.app.state.settings)
    ctx = SubscriberCtx(
        last_event_id=request.headers.get("last-event-id"),
        client_ip=request.client.host if request.client else None,
    )
    return streamer.stream(request, config, ctx)
