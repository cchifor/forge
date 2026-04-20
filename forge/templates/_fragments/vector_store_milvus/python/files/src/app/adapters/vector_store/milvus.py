"""Milvus adapter for the VectorStorePort.

Uses a collection-per-tenant isolation pattern. Vector metadata is
stored as dynamic fields (Milvus 2.3+) so the adapter doesn't need to
declare every metadata key up front.
"""

from __future__ import annotations

from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusClient,
    connections,
    utility,
)

from app.ports.vector_store import VectorHit, VectorStorePort


class MilvusAdapter(VectorStorePort):
    def __init__(self, uri: str, token: str, collection_prefix: str) -> None:
        # Use the high-level MilvusClient for simpler CRUD; fall back to
        # connections.connect for ensure_collection since schema setup
        # is easier with the low-level API.
        self._client = MilvusClient(uri=uri, token=token or None)
        self._uri = uri
        self._token = token
        self._prefix = collection_prefix

    def _collection_name(self, tenant_id: str) -> str:
        return f"{self._prefix}_{tenant_id}".replace("-", "_")

    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None:
        name = self._collection_name(tenant_id)
        rows = [
            {
                "id": id_,
                "vector": vec,
                "text": text,
                **meta,
            }
            for id_, vec, text, meta in vectors
        ]
        self._client.upsert(collection_name=name, data=rows)

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        name = self._collection_name(tenant_id)
        filter_expr = _filters_to_expr(filters) if filters else None
        results = self._client.search(
            collection_name=name,
            data=[embedding],
            limit=top_k,
            filter=filter_expr or "",
            output_fields=["*"],
        )
        hits: list[VectorHit] = []
        # MilvusClient returns a list of lists (one per query vector).
        for match in (results[0] if results else []):
            entity = match.get("entity", {})
            text = str(entity.pop("text", ""))
            entity.pop("vector", None)
            hits.append(
                VectorHit(
                    id=str(match.get("id", "")),
                    score=float(match.get("distance", 0.0)),
                    text=text,
                    metadata=entity,
                )
            )
        return hits

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None:
        name = self._collection_name(tenant_id)
        self._client.delete(collection_name=name, ids=ids)

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None:
        name = self._collection_name(tenant_id)
        # connections.connect is needed for utility.has_collection / Collection.
        connections.connect(alias="default", uri=self._uri, token=self._token or None)
        if utility.has_collection(name):
            return

        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        ]
        schema = CollectionSchema(fields=fields, enable_dynamic_field=True)
        collection = Collection(name=name, schema=schema)
        collection.create_index(
            field_name="vector",
            index_params={"metric_type": "COSINE", "index_type": "HNSW", "params": {"M": 8, "efConstruction": 64}},
        )
        collection.load()


def _filters_to_expr(filters: dict[str, Any]) -> str:
    """Convert a flat dict of filters into a Milvus boolean expression."""
    parts = []
    for key, value in filters.items():
        if isinstance(value, str):
            parts.append(f'{key} == "{value}"')
        elif isinstance(value, bool):
            parts.append(f"{key} == {str(value).lower()}")
        else:
            parts.append(f"{key} == {value}")
    return " && ".join(parts)
