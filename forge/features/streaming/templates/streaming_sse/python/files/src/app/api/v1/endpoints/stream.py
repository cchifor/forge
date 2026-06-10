"""Browser-bound CloudEvent stream.

GET /api/v1/stream — ``text/event-stream`` of CloudEvents. Browser
clients connect with an ``EventSource``; ``Last-Event-ID`` triggers
replay from a configured replay provider (none by default).

Auth-gated: the stream carries domain events, so it requires an
authenticated user (``Depends(get_current_user)``). NOTE: per-tenant
filtering of the event bus is a follow-up — today an authenticated user
sees the configured stream; do not enable this feature on a shared
multi-tenant bus without adding subscriber-side tenant filtering.
"""

from __future__ import annotations

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Request
from forge_core.security.auth import get_current_user

from app.streaming import CloudEventStreamer, SubscriberCtx, default_stream_config

# DishkaRoute resolves ``FromDishka[...]`` params from the app-scoped
# container. Plain ``Depends()`` would make FastAPI introspect
# ``CloudEventStreamer.__init__`` (bus: EventBusLike) and choke on the
# Protocol as a Pydantic field type — the streamer is a DI singleton, not a
# request body.
router = APIRouter(
    tags=["stream"],
    route_class=DishkaRoute,
    dependencies=[Depends(get_current_user)],
)


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
