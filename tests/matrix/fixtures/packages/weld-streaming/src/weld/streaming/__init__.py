"""weld.streaming stub."""

from dataclasses import dataclass
from typing import Any


@dataclass
class StreamConfig:
    """Stub stream-fan-out config."""

    topic: str = ""
    bus: Any = None


@dataclass
class SubscriberCtx:
    """Stub subscriber context."""

    subject: str = ""


class CloudEventStreamer:
    """Stub SSE fan-out streamer."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def subscribe(self, *args: Any, **kwargs: Any) -> Any: ...

    async def publish(self, *args: Any, **kwargs: Any) -> None: ...
