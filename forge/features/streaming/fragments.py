"""Streaming fragments — SSE fanout of CloudEvents (vendored, weld-free).

``streaming_sse`` ships a self-contained ``CloudEventStreamer`` that
composes ``sse-starlette`` (heartbeat / framing / disconnect) with bus
subscription, ``Last-Event-ID`` replay, an optional filter, a lifetime
cap, and graceful backpressure handling. The mechanism is vendored into
each generated project (``src/app/streaming/``) and imports only the
stdlib + sse-starlette + starlette (+ the duck-typed ``app.events`` bus)
— no private SDKs, and tenant context on ``SubscriberCtx`` is optional.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="streaming_sse",
            depends_on=("events_core",),
            capabilities=("postgres",),
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("streaming_sse", "python"),
                    # weld-streaming dropped — the streamer is vendored.
                    # sse-starlette is the only third-party dep (SSE wire
                    # framing + heartbeat).
                    dependencies=("sse-starlette>=2.1.0",),
                    env_vars=(
                        ("STREAMING_HEARTBEAT_S", "15"),
                        ("STREAMING_QUEUE_MAX", "1024"),
                    ),
                ),
            },
        )
    )
