"""Plain-PostgreSQL vector store — no pgvector extension required.

Embeddings are serialized as JSONB arrays and similarity is scored in Python
after fetching candidate rows (filtered to the caller's tenant). Acceptable
up to a few hundred thousand chunks per tenant; beyond that, switch to
``rag_pipeline`` (pgvector + HNSW) or ``rag_qdrant``.

The math is straightforward cosine similarity — unit-normalize query and
candidate, dot product, sort. No numpy dependency (RAG already depends on
it transitively via openai, but we don't want to force it on projects that
only enable this backend).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models.rag_postgresql_document import RagPgDocumentChunk


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    na = _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


@dataclass(frozen=True)
class PgHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    doc_name: str
    content: str
    score: float
    metadata: dict[str, Any] | None


async def store_chunks(
    *,
    session: AsyncSession,
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
    for idx, (content, vector) in enumerate(zip(chunks, embeddings, strict=True)):
        session.add(
            RagPgDocumentChunk(
                id=uuid.uuid4(),
                document_id=document_id,
                doc_name=doc_name,
                chunk_index=idx,
                content=content,
                metadata_json=metadata,
                # Force plain Python floats so JSONB serialization is stable
                # across numpy-array and tuple inputs.
                embedding=[float(x) for x in vector],
                customer_id=customer_id,
                user_id=user_id,
            )
        )
    await session.flush()
    return len(chunks)


async def search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    top_k: int = 5,
    customer_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    # Safety rail: we pull up to this many candidates before scoring. Keeps
    # memory bounded even if a tenant has a large corpus.
    candidate_limit: int = 2000,
) -> list[PgHit]:
    stmt = select(
        RagPgDocumentChunk.id,
        RagPgDocumentChunk.document_id,
        RagPgDocumentChunk.doc_name,
        RagPgDocumentChunk.content,
        RagPgDocumentChunk.metadata_json,
        RagPgDocumentChunk.embedding,
    ).limit(candidate_limit)
    if customer_id is not None:
        stmt = stmt.where(RagPgDocumentChunk.customer_id == customer_id)
    if document_id is not None:
        stmt = stmt.where(RagPgDocumentChunk.document_id == document_id)

    result = await session.execute(stmt)
    scored: list[PgHit] = []
    for row in result.all():
        emb = row.embedding
        if not isinstance(emb, list):
            continue
        score = cosine_similarity(query_vector, emb)
        scored.append(
            PgHit(
                chunk_id=row.id,
                document_id=row.document_id,
                doc_name=row.doc_name,
                content=row.content,
                score=score,
                metadata=row.metadata_json,
            )
        )
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[:top_k]
