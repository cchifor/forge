"""``weld.core.persistence.db.aio.AsyncDatabase`` stub."""
from typing import Any


class AsyncDatabase:
    """Stub DB connection holder."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def __aenter__(self) -> "AsyncDatabase":
        return self

    async def __aexit__(self, *args: Any) -> None: ...

    async def execute(self, *args: Any, **kwargs: Any) -> Any: ...

    async def fetch_one(self, *args: Any, **kwargs: Any) -> Any: ...

    async def fetch_all(self, *args: Any, **kwargs: Any) -> Any: ...

    async def close(self) -> None: ...
