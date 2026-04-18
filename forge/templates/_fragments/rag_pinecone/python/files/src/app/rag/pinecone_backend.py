"""Pinecone vector-store backend.

Uses the ``pinecone`` Python SDK with its ``PineconeAsyncio`` client for
non-blocking operations. Since Pinecone is always managed (no self-hosted
story), there's no collection/db bootstrap — users create the index in the
Pinecone console or via a one-off setup script and supply its name via
``PINECONE_INDEX``.

Namespaces provide tenant isolation — we route each ``customer_id`` to its
own Pinecone namespace, so tenant A's data is never in tenant B's query
space (cleaner than a filter-based approach).

Config:
  - ``PINECONE_API_KEY`` — required
  - ``PINECONE_INDEX`` — the pre-created index name (default ``forge-rag``)
  - ``PINECONE_ENVIRONMENT`` — legacy pod-based deployments; serverless
    indexes ignore this
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _api_key() -> str:
    return os.environ.get("PINECONE_API_KEY", "")


def _index_name() -> str:
    return os.environ.get("PINECONE_INDEX", "forge-rag")


_client = None


async def _get_index():
    global _client
    if _client is None:
        from pinecone import PineconeAsyncio  # type: ignore

        if not _api_key():
            raise RuntimeError("PINECONE_API_KEY not set")
        _client = PineconeAsyncio(api_key=_api_key())
    return _client.IndexAsyncio(name=_index_name())


def _namespace(customer_id: uuid.UUID | None) -> str:
    """Pinecone namespaces provide hard tenant isolation."""
    if customer_id is None:
        return "shared"
    return f"tenant-{customer_id}"


@dataclass(frozen=True)
class PineconeHit:
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
    index = await _get_index()
    vectors = [
        {
            "id": str(uuid.uuid4()),
            "values": list(vec),
            "metadata": {
                "content": content,
                "document_id": str(document_id),
                "doc_name": doc_name,
                "chunk_index": idx,
                "user_id": str(user_id),
                **(metadata or {}),
            },
        }
        for idx, (content, vec) in enumerate(zip(chunks, embeddings, strict=True))
    ]
    await index.upsert(vectors=vectors, namespace=_namespace(customer_id))
    return len(vectors)


async def search(
    query_vector: list[float],
    *,
    top_k: int = 5,
    customer_id: uuid.UUID | None = None,
) -> list[PineconeHit]:
    index = await _get_index()
    response = await index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=_namespace(customer_id),
        include_metadata=True,
        include_values=False,
    )

    hits: list[PineconeHit] = []
    for match in response.matches or []:
        meta = match.metadata or {}
        try:
            doc_uuid = uuid.UUID(str(meta.get("document_id", "")))
        except (ValueError, TypeError):
            doc_uuid = uuid.uuid4()
        try:
            chunk_uuid = uuid.UUID(str(match.id))
        except (ValueError, TypeError):
            chunk_uuid = uuid.uuid4()
        hits.append(
            PineconeHit(
                chunk_id=chunk_uuid,
                document_id=doc_uuid,
                doc_name=str(meta.get("doc_name", "unknown")),
                content=str(meta.get("content", "")),
                score=float(match.score or 0.0),
                metadata={
                    k: v
                    for k, v in meta.items()
                    if k not in {"document_id", "doc_name", "chunk_index", "content", "user_id"}
                }
                or None,
            )
        )
    return hits
