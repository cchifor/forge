"""``weld.core.persistence.db.aio.AsyncDatabase`` stub."""

from typing import Any


class AsyncDatabase:
    """Stub DB connection holder."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    @classmethod
    def from_config(cls, _config: dict[str, Any]) -> "AsyncDatabase":
        """Construct from a Settings.db.model_dump() mapping.

        Mirrors the real ``weld.core.persistence.db.aio.AsyncDatabase``
        factory signature. The generated python-service-template calls
        ``AsyncDatabase.from_config(settings.db.model_dump())`` inside
        ``src/app/core/ioc/infra.py``; without this method the matrix
        smoke lane's api container exits 3 on startup.
        """
        return cls()

    async def __aenter__(self) -> "AsyncDatabase":
        return self

    async def __aexit__(self, *args: Any) -> None: ...

    async def execute(self, *args: Any, **kwargs: Any) -> Any: ...

    async def fetch_one(self, *args: Any, **kwargs: Any) -> Any: ...

    async def fetch_all(self, *args: Any, **kwargs: Any) -> Any: ...

    async def close(self) -> None: ...
