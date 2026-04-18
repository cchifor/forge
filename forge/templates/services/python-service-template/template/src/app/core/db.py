"""Process-wide accessor for the async session factory.

Dishka is the authoritative source of the `async_sessionmaker` (built by
`InfraProvider.get_session_factory`). But code that runs *outside* a
request scope — agent tool handlers, BullMQ / Taskiq / Apalis workers,
the admin panel bootstrap — can't use `FromDishka[...]`. They call
`get_session_factory()` here.

`AppLifecycle._on_startup` publishes the container-built factory via
`set_session_factory(...)` before any request or task can run. If a
caller asks for the factory before startup (e.g., a unit test that
imports a tool), they get a clear error instead of a dangling None.

Crucially: **one engine, one pool** — no fragment should ever call
`create_async_engine` on its own.
"""

from __future__ import annotations

from typing import Any

_session_factory: Any | None = None


def set_session_factory(factory: Any) -> None:
    """Publish the container-built session factory. Called exactly once
    from `AppLifecycle._on_startup`.
    """
    global _session_factory
    _session_factory = factory


def get_session_factory() -> Any:
    """Return the shared session factory.

    Raises `RuntimeError` if the app hasn't started yet — that's almost
    always a wiring bug (a tool imported before lifecycle bootstrap).
    """
    if _session_factory is None:
        raise RuntimeError(
            "app.core.db.get_session_factory() called before startup. "
            "Ensure AppLifecycle.bootstrap + lifespan have run, or "
            "explicitly set_session_factory() in a test fixture."
        )
    return _session_factory


def reset_session_factory() -> None:
    """Test hook; clears the shared reference so the next startup can publish anew."""
    global _session_factory
    _session_factory = None
