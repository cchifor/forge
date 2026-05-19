"""``weld.core.persistence.uow.aio`` stubs."""

from typing import Any


class _StubRepoRegistry:
    """Stub repository registry returned by ``AsyncUnitOfWork.repo``.

    The generated service's services use the registry in two shapes:

      * ``repo = uow.repo(HealthRepository)`` — repo-by-class factory
        call (the python-service-template's actual usage); returns a
        stub repo instance.
      * ``uow.repo.<name>.<op>(...)`` — attribute-chained access, kept
        permissive so unrelated reachable code paths don't crash.

    The matrix smoke contract only verifies the api container reaches a
    200/503 readiness response, not that queries return real rows, so
    the stub repo's ``__getattr__`` returns another stub (callable,
    awaitable-via-no-op) that swallows whatever the caller does.
    """

    def __call__(self, *_args: Any, **_kwargs: Any) -> "_StubRepoRegistry":
        return self

    def __getattr__(self, _name: str) -> Any:
        return self

    def __await__(self):
        # Allow ``await uow.repo.something()`` patterns to no-op rather
        # than crash. Yields nothing and returns the registry itself.
        if False:
            yield  # type: ignore[unreachable]
        return self


class AsyncUnitOfWork:
    """Stub async transaction scope."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._repo_impl = _StubRepoRegistry()

    @property
    def repo(self) -> Any:
        # Typed ``Any`` so the generated service's repo-typed annotations
        # don't trip ``ty check`` on the stub (same pattern as
        # ``AsyncDatabase.session_factory``).
        return self._repo_impl

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
