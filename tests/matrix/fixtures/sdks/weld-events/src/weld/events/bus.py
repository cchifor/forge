"""``weld.events.bus`` — explicit-import path for the in-memory bus."""
from typing import Any

from . import EventBus


class InMemoryEventBus(EventBus):
    """Process-local stub bus."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._published: list[Any] = []

    async def publish(self, event: Any, *args: Any, **kwargs: Any) -> None:
        self._published.append(event)
