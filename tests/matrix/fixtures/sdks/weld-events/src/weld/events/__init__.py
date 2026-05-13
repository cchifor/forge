"""weld.events namespace stub."""
from typing import Any


class EventBus:
    """Stub event bus."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def publish(self, *args: Any, **kwargs: Any) -> None: ...

    async def subscribe(self, *args: Any, **kwargs: Any) -> Any: ...


class OutboxStore:
    """Stub outbox store."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def add(self, *args: Any, **kwargs: Any) -> None: ...

    async def claim(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def mark_published(self, *args: Any, **kwargs: Any) -> None: ...


class OutboxRelay:
    """Stub outbox relay."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def relay_once(self) -> int:
        return 0

    async def run(self, *args: Any, **kwargs: Any) -> None: ...
