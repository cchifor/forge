"""Weaviate v4 async vector-store backend.

Uses the ``weaviate-client`` Python SDK (v4+). We manage our own vectors
(``vectorizer=None``) so the embeddings from ``rag_pipeline.embeddings``
drive retrieval directly — no server-side vectorization.

Config:
  - ``WEAVIATE_URL`` — full HTTP URL to the Weaviate instance
  - ``WEAVIATE_API_KEY`` — optional bearer token (Weaviate Cloud)
  - ``WEAVIATE_COLLECTION`` — collection / class name (default ``ForgeRag``)
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _url() -> str:
    return os.environ.get("WEAVIATE_URL", "http://weaviate:8080")


def _api_key() -> str | None:
    k = os.environ.get("WEAVIATE_API_KEY")
    return k or None


def _collection() -> str:
    # Weaviate class names must be PascalCase.
    raw = os.environ.get("WEAVIATE_COLLECTION", "ForgeRag")
    return raw


_client = None
_ensured: set[str] = set()


async def _get_client():
    global _client
    if _client is not None:
        return _client
    import weaviate  # type: ignore
    from weaviate.classes.init import Auth  # type: ignore

    parsed = urlparse(_url())
    secure = parsed.scheme == "https"
    host = parsed.hostname or "weaviate"
    port = parsed.port or (443 if secure else 8080)

    auth = Auth.api_key(_api_key()) if _api_key() else None
    _client = weaviate.use_async_with_custom(
        http_host=host,
        http_port=port,
        http_secure=secure,
        grpc_host=host,
        grpc_port=50051,
        grpc_secure=secure,
        auth_credentials=auth,
    )
    await _client.connect()
    return _client


async def ensure_collection() -> None:
    name = _collection()
    if name in _ensured:
        return
    from weaviate.classes.config import (  # type: ignore
        Configure,
        DataType,
        Property,
        VectorDistances,
    )

    client = await _get_client()
    if await client.collections.exists(name):
        _ensured.add(name)
        return
    await client.collections.create(
        name=name,
        properties=[
            Property(name="content", data_type=DataType.TEXT),
            Property(name="document_id", data_type=DataType.UUID),
            Property(name="doc_name", data_type=DataType.TEXT),
            Property(name="customer_id", data_type=DataType.UUID),
            Property(name="chunk_index", data_type=DataType.INT),
        ],
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=VectorDistances.COSINE
        ),
    )
    _ensured.add(name)
    logger.info("weaviate: created collection %s", name)


@dataclass(frozen=True)
class WeaviateHit:
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
    client = await _get_client()
    coll = client.collections.get(_collection())

    from weaviate.classes.data import DataObject  # type: ignore

    objects = [
        DataObject(
            properties={
                "content": content,
                "document_id": str(document_id),
                "doc_name": doc_name,
                "customer_id": str(customer_id),
                "chunk_index": idx,
            },
            vector=list(vec),
        )
        for idx, (content, vec) in enumerate(zip(chunks, embeddings, strict=True))
    ]
    await coll.data.insert_many(objects)
    return len(objects)


async def search(
    query_vector: list[float],
    *,
    top_k: int = 5,
    customer_id: uuid.UUID | None = None,
) -> list[WeaviateHit]:
    from weaviate.classes.query import Filter, MetadataQuery  # type: ignore

    await ensure_collection()
    client = await _get_client()
    coll = client.collections.get(_collection())

    filters = None
    if customer_id is not None:
        filters = Filter.by_property("customer_id").equal(str(customer_id))

    result = await coll.query.near_vector(
        near_vector=query_vector,
        limit=top_k,
        return_metadata=MetadataQuery(distance=True),
        filters=filters,
    )

    hits: list[WeaviateHit] = []
    for obj in result.objects:
        props = obj.properties or {}
        distance = getattr(obj.metadata, "distance", 0.0) if obj.metadata else 0.0
        try:
            doc_uuid = uuid.UUID(str(props.get("document_id", "")))
        except (ValueError, TypeError):
            doc_uuid = uuid.uuid4()
        hits.append(
            WeaviateHit(
                chunk_id=obj.uuid if isinstance(obj.uuid, uuid.UUID) else uuid.uuid4(),
                document_id=doc_uuid,
                doc_name=str(props.get("doc_name", "unknown")),
                content=str(props.get("content", "")),
                score=max(0.0, 1.0 - float(distance)),
                metadata=None,
            )
        )
    return hits
