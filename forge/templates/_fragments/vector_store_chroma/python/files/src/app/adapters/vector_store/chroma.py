"""Chroma adapter for the VectorStorePort.

Collection-per-tenant isolation matching the Qdrant adapter's pattern.
"""

from __future__ import annotations

from typing import Any

import chromadb
from chromadb.config import Settings

from app.ports.vector_store import VectorHit, VectorStorePort


class ChromaAdapter(VectorStorePort):
    def __init__(
        self,
        url: str,
        collection_prefix: str,
        tenant: str,
        database: str,
    ) -> None:
        # Parse host:port out of the URL — chromadb.HttpClient takes them separately.
        from urllib.parse import urlparse

        parsed = urlparse(url)
        self._client = chromadb.HttpClient(
            host=parsed.hostname or "chroma",
            port=parsed.port or 8000,
            tenant=tenant,
            database=database,
            settings=Settings(anonymized_telemetry=False),
        )
        self._prefix = collection_prefix

    def _collection_name(self, tenant_id: str) -> str:
        return f"{self._prefix}_{tenant_id}"

    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None:
        col = self._client.get_or_create_collection(self._collection_name(tenant_id))
        ids = [v[0] for v in vectors]
        embeddings = [v[1] for v in vectors]
        documents = [v[2] for v in vectors]
        metadatas = [v[3] for v in vectors]
        col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)  # ty: ignore[invalid-argument-type]

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        col = self._client.get_or_create_collection(self._collection_name(tenant_id))
        result = col.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where=filters,
        )
        hits: list[VectorHit] = []
        # Chroma returns lists-of-lists (one per query). We only ever query one.
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        for i, id_ in enumerate(ids):
            hits.append(
                VectorHit(
                    id=str(id_),
                    # Chroma returns distance, not similarity — lower is better.
                    # Callers who want a similarity score can invert: 1 - score.
                    score=float(distances[i]) if i < len(distances) else 0.0,
                    text=str(documents[i]) if i < len(documents) else "",
                    metadata=dict(metadatas[i]) if i < len(metadatas) and metadatas[i] else {},
                )
            )
        return hits

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None:
        col = self._client.get_or_create_collection(self._collection_name(tenant_id))
        col.delete(ids=ids)

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None:
        # Chroma creates collections implicitly on first use; the dim is
        # inferred from the first upsert. get_or_create is idempotent.
        self._client.get_or_create_collection(self._collection_name(tenant_id))
