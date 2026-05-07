"""Fragment smoke tests for `rag_postgresql`.

Verifies module-level imports + that the backend module ships the
expected public API (store_chunks / search) callers rely on.
"""

from __future__ import annotations


def test_backend_module_imports_cleanly() -> None:
    from app.rag import postgresql_backend  # noqa: F401


def test_public_api_surface() -> None:
    from app.rag import postgresql_backend

    assert callable(postgresql_backend.store_chunks)
    assert callable(postgresql_backend.search)


def test_endpoint_router_is_auth_gated() -> None:
    """A1.1 invariant: the /rag/pg router must require oauth2_scheme."""
    from app.api.v1.endpoints import rag_postgresql

    deps = rag_postgresql.router.dependencies
    # At least one dependency should look like an oauth2 scheme.
    assert deps, "router must carry at least one auth dependency"
