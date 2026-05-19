"""``weld.core.persistence.db.aio.AsyncDatabase`` stub."""

from typing import Any


class _StubSession:
    """Stub ``sqlalchemy.ext.asyncio.AsyncSession``.

    The generated IoC's ``get_db_session`` provider yields one of these
    and awaits ``.close()`` on teardown. The matrix smoke contract never
    actually issues queries, so we only need ``close`` here.
    """

    async def close(self) -> None: ...


class _StubSessionFactory:
    """Stub ``async_sessionmaker``: callable that returns an AsyncSession."""

    def __call__(self) -> _StubSession:
        return _StubSession()


class AsyncDatabase:
    """Stub DB connection holder.

    Mirrors the subset of the real ``weld.core.persistence.db.aio.AsyncDatabase``
    that the generated python-service-template's IoC bootstrap touches at
    container startup (see ``src/app/core/ioc/infra.py``):

      * ``AsyncDatabase.from_config(dict)``  — classmethod factory
      * ``db.session_factory``               — callable returning an AsyncSession
      * ``await db.dispose()``               — shutdown hook on the provider yield

    The matrix smoke lane only verifies the api container starts (no
    real queries are issued), so the methods are no-ops; the session
    factory returns a stub session whose ``close`` is also a no-op.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._session_factory_impl = _StubSessionFactory()

    @property
    def session_factory(self) -> Any:
        # Typed as ``Any`` so the generated service's
        # ``get_session_factory -> async_sessionmaker`` annotation
        # (referencing the real sqlalchemy type) doesn't trip
        # ``ty check`` on the stub. A property returning ``Any`` is
        # what survives ty's attribute-type inference; a directly
        # assigned attribute resolves to the concrete value type
        # regardless of the declared annotation.
        return self._session_factory_impl

    @classmethod
    def from_config(cls, _config: dict[str, Any]) -> "AsyncDatabase":
        return cls()

    async def dispose(self) -> None: ...

    async def __aenter__(self) -> "AsyncDatabase":
        return self

    async def __aexit__(self, *args: Any) -> None: ...

    async def execute(self, *args: Any, **kwargs: Any) -> Any: ...

    async def fetch_one(self, *args: Any, **kwargs: Any) -> Any: ...

    async def fetch_all(self, *args: Any, **kwargs: Any) -> Any: ...

    async def close(self) -> None: ...
