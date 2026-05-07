"""Vector store port — the capability contract every adapter implements.

Adapters live under ``app/adapters/vector_store/<provider>.py`` and
register themselves with the dependency container (``app/core/container.py``)
based on the ``VECTOR_STORE_PROVIDER`` environment variable. The rest of
the application depends on this Protocol, never on a specific provider.

See ``docs/architecture-decisions/ADR-002-ports-and-adapters.md`` for the
why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorHit:
    """One retrieval result — id, score, text, and arbitrary metadata."""

    id: str
    score: float
    text: str
    metadata: dict[str, Any]


class VectorStorePort(Protocol):
    """Vector-store surface used by the RAG pipeline.

    Adapters implement this Protocol. Adding a new adapter requires
    implementing the four methods below; no inheritance hierarchy.

    ``tenant_id`` is threaded through every call so multi-tenant
    isolation is the default — adapters either use a per-tenant
    collection/namespace or filter on a tenant column.
    """

    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None:
        """Upsert a batch of ``(id, embedding, text, metadata)`` tuples."""

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        """Search for the nearest ``top_k`` vectors and return ``VectorHit``s."""

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None:
        """Remove vectors by id for the given tenant."""

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None:
        """Create the backing collection / namespace if it doesn't exist."""
