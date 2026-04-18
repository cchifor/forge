"""Chroma vector-store backend.

Ships alongside pgvector and Qdrant (see `rag_pipeline` and `rag_qdrant`).
Users picking Chroma typically do so for its hosted option (Chroma Cloud)
or for local dev simplicity — the server runs in a single container with
no external deps.

Config via env:
  - ``CHROMA_URL`` — e.g. ``http://chroma:8000``  (default localhost:8000)
  - ``CHROMA_COLLECTION`` — collection name (default ``forge_rag``)
  - ``CHROMA_TENANT`` — optional Chroma tenant (default ``default_tenant``)
  - ``CHROMA_DATABASE`` — optional database (default ``default_database``)
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


def _parse_url() -> tuple[str, int, bool]:
    """Return (host, port, ssl)."""
    raw = os.environ.get("CHROMA_URL", "http://chroma:8000")
    parsed = urlparse(raw)
    ssl = parsed.scheme == "https"
    port = parsed.port or (443 if ssl else 80)
    host = parsed.hostname or "localhost"
    return host, port, ssl


def _collection() -> str:
    return os.environ.get("CHROMA_COLLECTION", "forge_rag")


_client = None


async def _get_client():
    global _client
    if _client is not None:
        return _client
    import chromadb  # type: ignore

    host, port, ssl = _parse_url()
    _client = await chromadb.AsyncHttpClient(
        host=host,
        port=port,
        ssl=ssl,
        tenant=os.environ.get("CHROMA_TENANT", "default_tenant"),
        database=os.environ.get("CHROMA_DATABASE", "default_database"),
    )
    return _client


@dataclass(frozen=True)
class ChromaHit:
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
    client = await _get_client()
    collection = await client.get_or_create_collection(name=_collection())

    ids = [str(uuid.uuid4()) for _ in chunks]
    metas = [
        {
            "document_id": str(document_id),
            "doc_name": doc_name,
            "chunk_index": idx,
            "customer_id": str(customer_id),
            "user_id": str(user_id),
            **(metadata or {}),
        }
        for idx in range(len(chunks))
    ]
    await collection.add(
        ids=ids,
        embeddings=[list(v) for v in embeddings],
        documents=list(chunks),
        metadatas=metas,
    )
    return len(chunks)


async def search(
    query_vector: list[float],
    *,
    top_k: int = 5,
    customer_id: uuid.UUID | None = None,
) -> list[ChromaHit]:
    client = await _get_client()
    collection = await client.get_or_create_collection(name=_collection())

    where: dict[str, Any] | None = None
    if customer_id is not None:
        where = {"customer_id": str(customer_id)}

    result = await collection.query(
        query_embeddings=[query_vector],
        n_results=top_k,
        where=where,
    )

    hits: list[ChromaHit] = []
    # Chroma returns top-level arrays indexed by query; we ran one query.
    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]
    for raw_id, content, meta, dist in zip(ids, docs, metas, dists, strict=False):
        meta = meta or {}
        try:
            chunk_uuid = uuid.UUID(str(raw_id))
        except (ValueError, TypeError):
            chunk_uuid = uuid.uuid4()
        try:
            doc_uuid = uuid.UUID(str(meta.get("document_id")))
        except (ValueError, TypeError):
            doc_uuid = uuid.uuid4()
        hits.append(
            ChromaHit(
                chunk_id=chunk_uuid,
                document_id=doc_uuid,
                doc_name=str(meta.get("doc_name", "unknown")),
                content=str(content or ""),
                # Chroma returns L2 distance by default; convert to a score in [0, 1].
                score=max(0.0, 1.0 - float(dist or 0.0)),
                metadata={
                    k: v
                    for k, v in meta.items()
                    if k not in {"document_id", "doc_name", "chunk_index", "customer_id", "user_id"}
                }
                or None,
            )
        )
    return hits
