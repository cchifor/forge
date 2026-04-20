"""Pinecone adapter for the VectorStorePort.

Uses Pinecone's namespace feature for per-tenant isolation — a single
index hosts every tenant, and vectors land in ``namespace=tenant_id``.
Cheaper than a collection-per-tenant pattern on Pinecone's pricing
tiers.
"""

from __future__ import annotations

from typing import Any

from pinecone import Pinecone, ServerlessSpec

from app.ports.vector_store import VectorHit, VectorStorePort


class PineconeAdapter(VectorStorePort):
    def __init__(
        self,
        api_key: str,
        index_name: str,
        environment: str = "",
        cloud: str = "aws",
        region: str = "us-east-1",
    ) -> None:
        self._client = Pinecone(api_key=api_key)
        self._index_name = index_name
        self._environment = environment
        self._cloud = cloud
        self._region = region
        # Lazy init — index handle fetched on first call since it may
        # not exist yet (ensure_collection creates it).
        self._index = None

    def _get_index(self):
        if self._index is None:
            self._index = self._client.Index(self._index_name)
        return self._index

    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None:
        index = self._get_index()
        items = [
            {
                "id": id_,
                "values": vec,
                "metadata": {"text": text, **meta},
            }
            for id_, vec, text, meta in vectors
        ]
        index.upsert(vectors=items, namespace=tenant_id)

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        index = self._get_index()
        result = index.query(
            vector=embedding,
            top_k=top_k,
            namespace=tenant_id,
            filter=filters,
            include_metadata=True,
        )
        hits: list[VectorHit] = []
        for match in result.get("matches", []):
            metadata = match.get("metadata") or {}
            text = str(metadata.pop("text", ""))
            hits.append(
                VectorHit(
                    id=str(match["id"]),
                    score=float(match.get("score", 0.0)),
                    text=text,
                    metadata=metadata,
                )
            )
        return hits

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None:
        index = self._get_index()
        index.delete(ids=ids, namespace=tenant_id)

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None:
        # Pinecone "collection" = index. Namespaces are per-tenant and
        # created implicitly on first upsert, so ensuring the index
        # exists is enough.
        existing = [idx.name for idx in self._client.list_indexes()]
        if self._index_name in existing:
            return
        self._client.create_index(
            name=self._index_name,
            dimension=dim,
            metric="cosine",
            spec=ServerlessSpec(cloud=self._cloud, region=self._region),
        )
