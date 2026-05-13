"""``weld.core.persistence.uow.aio`` stubs."""

from typing import Any


class AsyncUnitOfWork:
    """Stub async transaction scope."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def __aenter__(self) -> "AsyncUnitOfWork":
        return self

    async def __aexit__(self, *args: Any) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class HealthRepository:
    """Stub health-probe repo."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def check(self) -> bool:
        return True
