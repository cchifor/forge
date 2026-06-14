"""``weld.core.discovery`` — service-registry client stub."""

from typing import Any


class Discovery:
    """Stub for service-discovery client."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def register(self, *args: Any, **kwargs: Any) -> None: ...

    async def deregister(self, *args: Any, **kwargs: Any) -> None: ...

    async def lookup(self, *args: Any, **kwargs: Any) -> Any: ...
