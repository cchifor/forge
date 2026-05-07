"""Qdrant vector-store backend — parallel to the pgvector store.

The primary rag_pipeline feature uses pgvector (rides the existing Postgres
service); this module adds Qdrant as a drop-in alternative when users need
the purpose-built vector DB (higher throughput, filterable payloads, HNSW
build-options). Use via /api/v1/rag/qdrant/ingest + /search endpoints, or
wire the module into your own handlers to make Qdrant the primary backend.

Config via env:
  - ``QDRANT_URL`` — e.g. ``http://qdrant:6333``
  - ``QDRANT_API_KEY`` — optional for Qdrant Cloud
  - ``QDRANT_COLLECTION`` — name of the collection to use / create
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _url() -> str:
    return os.environ.get("QDRANT_URL", "http://qdrant:6333")


def _collection() -> str:
    return os.environ.get("QDRANT_COLLECTION", "forge_rag")


def _dim() -> int:
    try:
        return int(os.environ.get("EMBEDDING_DIM", "1536"))
    except ValueError:
        return 1536


_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    from qdrant_client import AsyncQdrantClient  # type: ignore

    api_key = os.environ.get("QDRANT_API_KEY") or None
    _client = AsyncQdrantClient(url=_url(), api_key=api_key)
    return _client


async def ensure_collection() -> None:
    """Create the collection idempotently if it doesn't exist yet."""
    from qdrant_client.http.exceptions import UnexpectedResponse  # type: ignore
    from qdrant_client.models import Distance, VectorParams  # type: ignore

    client = _get_client()
    name = _collection()
    try:
        await client.get_collection(collection_name=name)
    except UnexpectedResponse:
        logger.info("qdrant: creating collection %s", name)
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=_dim(), distance=Distance.COSINE),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("qdrant: get_collection failed (%s); attempting create", e)
        try:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=_dim(), distance=Distance.COSINE),
            )
        except Exception as e2:  # noqa: BLE001
            logger.error("qdrant: create_collection failed: %s", e2)
            raise


@dataclass(frozen=True)
class QdrantHit:
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
    """Insert one point per chunk. Returns number of points written."""
    from qdrant_client.models import PointStruct  # type: ignore

    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
        )
    await ensure_collection()
    client = _get_client()
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=list(vector),
            payload={
                "document_id": str(document_id),
                "doc_name": doc_name,
                "chunk_index": idx,
                "content": content,
                "customer_id": str(customer_id),
                "user_id": str(user_id),
                **(metadata or {}),
            },
        )
        for idx, (content, vector) in enumerate(zip(chunks, embeddings, strict=True))
    ]
    await client.upsert(collection_name=_collection(), points=points, wait=True)
    return len(points)


async def search(
    query_vector: list[float],
    *,
    top_k: int = 5,
    customer_id: uuid.UUID | None = None,
) -> list[QdrantHit]:
    from qdrant_client.models import FieldCondition, Filter, MatchValue  # type: ignore

    client = _get_client()
    must: list[Any] = []
    if customer_id is not None:
        must.append(
            FieldCondition(key="customer_id", match=MatchValue(value=str(customer_id)))
        )
    query_filter = Filter(must=must) if must else None

    results = await client.search(
        collection_name=_collection(),
        query_vector=query_vector,
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )
    hits: list[QdrantHit] = []
    for point in results:
        payload = point.payload or {}
        try:
            doc_uuid = uuid.UUID(str(payload.get("document_id")))
        except (ValueError, TypeError):
            doc_uuid = uuid.uuid4()
        try:
            chunk_uuid = uuid.UUID(str(point.id))
        except (ValueError, TypeError):
            chunk_uuid = uuid.uuid4()
        hits.append(
            QdrantHit(
                chunk_id=chunk_uuid,
                document_id=doc_uuid,
                doc_name=str(payload.get("doc_name", "unknown")),
                content=str(payload.get("content", "")),
                score=float(point.score),
                metadata={
                    k: v
                    for k, v in payload.items()
                    if k not in {"document_id", "doc_name", "chunk_index", "content", "customer_id", "user_id"}
                }
                or None,
            )
        )
    return hits
