"""Milvus vector-store backend.

Uses ``pymilvus.AsyncMilvusClient`` for non-blocking operations. Assumes a
single collection per service (override via ``MILVUS_COLLECTION``);
partition-per-tenant would be a natural next step for strict isolation.

Schema bootstrap: on first store, the collection is created with the
configured ``EMBEDDING_DIM``. An HNSW index is built on the vector column
automatically.

Config:
  - ``MILVUS_URI`` — e.g. ``http://milvus:19530`` or ``milvus://...``
  - ``MILVUS_TOKEN`` — optional for Zilliz Cloud / secured deployments
  - ``MILVUS_COLLECTION`` — collection name (default ``forge_rag``)
  - ``EMBEDDING_DIM`` — vector dimension (shared with rag_pipeline)
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _uri() -> str:
    return os.environ.get("MILVUS_URI", "http://milvus:19530")


def _token() -> str | None:
    tok = os.environ.get("MILVUS_TOKEN")
    return tok or None


def _collection() -> str:
    return os.environ.get("MILVUS_COLLECTION", "forge_rag")


def _dim() -> int:
    try:
        return int(os.environ.get("EMBEDDING_DIM", "1536"))
    except ValueError:
        return 1536


_client = None
_collection_ready = False


def _get_client():
    global _client
    if _client is not None:
        return _client
    from pymilvus import AsyncMilvusClient  # type: ignore

    _client = AsyncMilvusClient(uri=_uri(), token=_token())
    return _client


async def ensure_collection() -> None:
    """Create the collection if it doesn't exist. Idempotent."""
    global _collection_ready
    if _collection_ready:
        return

    from pymilvus import DataType  # type: ignore

    client = _get_client()
    name = _collection()
    if await client.has_collection(collection_name=name):
        _collection_ready = True
        return

    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=_dim())
    schema.add_field("content", DataType.VARCHAR, max_length=65535)
    schema.add_field("document_id", DataType.VARCHAR, max_length=64)
    schema.add_field("doc_name", DataType.VARCHAR, max_length=500)
    schema.add_field("customer_id", DataType.VARCHAR, max_length=64)
    schema.add_field("chunk_index", DataType.INT64)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )

    await client.create_collection(
        collection_name=name,
        schema=schema,
        index_params=index_params,
    )
    _collection_ready = True
    logger.info("milvus: created collection %s", name)


@dataclass(frozen=True)
class MilvusHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    doc_name: str
    content: str
    score: float
    metadata: dict[str, Any] | None


async def store_chunks(
    *,
    document_id: uuid.UUID,
    doc_name: str,
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    chunks: Sequence[str],
    embeddings: Sequence[list[float]],
    metadata: dict | None = None,
) -> int:
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
        )
    await ensure_collection()
    client = _get_client()

    rows = [
        {
            "id": str(uuid.uuid4()),
            "embedding": list(vec),
            "content": content,
            "document_id": str(document_id),
            "doc_name": doc_name,
            "customer_id": str(customer_id),
            "chunk_index": idx,
            **(metadata or {}),
        }
        for idx, (content, vec) in enumerate(zip(chunks, embeddings, strict=True))
    ]
    await client.insert(collection_name=_collection(), data=rows)
    return len(rows)


async def search(
    query_vector: list[float],
    *,
    top_k: int = 5,
    customer_id: uuid.UUID | None = None,
) -> list[MilvusHit]:
    await ensure_collection()
    client = _get_client()

    filter_expr = ""
    if customer_id is not None:
        filter_expr = f'customer_id == "{customer_id}"'

    results = await client.search(
        collection_name=_collection(),
        data=[query_vector],
        anns_field="embedding",
        limit=top_k,
        output_fields=["id", "content", "document_id", "doc_name", "chunk_index"],
        filter=filter_expr,
        search_params={"metric_type": "COSINE"},
    )

    hits: list[MilvusHit] = []
    for batch in results:
        for match in batch:
            entity = match.get("entity", {}) if isinstance(match, dict) else {}
            score = float(match.get("distance", 0.0)) if isinstance(match, dict) else 0.0
            try:
                doc_uuid = uuid.UUID(entity.get("document_id", ""))
            except (ValueError, TypeError):
                doc_uuid = uuid.uuid4()
            try:
                chunk_uuid = uuid.UUID(entity.get("id", ""))
            except (ValueError, TypeError):
                chunk_uuid = uuid.uuid4()
            hits.append(
                MilvusHit(
                    chunk_id=chunk_uuid,
                    document_id=doc_uuid,
                    doc_name=str(entity.get("doc_name", "unknown")),
                    content=str(entity.get("content", "")),
                    # Milvus returns cosine similarity directly for metric COSINE.
                    score=score,
                    metadata=None,
                )
            )
    return hits
