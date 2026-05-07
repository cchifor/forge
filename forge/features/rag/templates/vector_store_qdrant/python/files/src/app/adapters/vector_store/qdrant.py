"""Qdrant adapter for the VectorStorePort.

Implements the port's contract against a Qdrant cluster. Collection is
per-tenant (``<collection_prefix>_<tenant_id>``) for hard isolation.
"""

from __future__ import annotations

from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from app.ports.vector_store import VectorHit, VectorStorePort


class QdrantAdapter(VectorStorePort):
    def __init__(self, url: str, api_key: str | None, collection_prefix: str) -> None:
        self._client = AsyncQdrantClient(url=url, api_key=api_key or None)
        self._prefix = collection_prefix

    def _collection(self, tenant_id: str) -> str:
        return f"{self._prefix}_{tenant_id}"

    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None:
        points = [
            PointStruct(id=id_, vector=vec, payload={"text": text, **meta})
            for id_, vec, text, meta in vectors
        ]
        await self._client.upsert(
            collection_name=self._collection(tenant_id),
            points=points,
        )

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        results = await self._client.search(
            collection_name=self._collection(tenant_id),
            query_vector=embedding,
            limit=top_k,
            query_filter=filters,
        )
        return [
            VectorHit(
                id=str(r.id),
                score=float(r.score),
                text=str((r.payload or {}).get("text", "")),
                metadata={k: v for k, v in (r.payload or {}).items() if k != "text"},
            )
            for r in results
        ]

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None:
        await self._client.delete(
            collection_name=self._collection(tenant_id),
            points_selector=ids,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None:
        name = self._collection(tenant_id)
        existing = await self._client.get_collections()
        if any(c.name == name for c in existing.collections):
            return
        await self._client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
