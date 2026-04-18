"""Read-path for RAG: embed a query and return top-k similar chunks.

Cosine distance matches the HNSW index the migration creates. Keep the
query shape simple; callers can stack filters before the similarity clause
for per-tenant or per-document scoping.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models.rag_document import RagDocumentChunk
from app.rag.embeddings import embed_one

logger = logging.getLogger(__name__)

_TOP_K_MIN = 1
_TOP_K_MAX = 100
_TOP_K_DEFAULT = 5


def _default_top_k() -> int:
    """Resolve `RAG_TOP_K`, clamped to [1, 100].

    An invalid or out-of-range value logs a warning and falls back to 5,
    rather than silently accepting a value that would later blow up as a
    SQL LIMIT 0 (empty result) or a 1000-row scan.
    """
    raw = os.environ.get("RAG_TOP_K")
    if raw is None:
        return _TOP_K_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        logger.warning("RAG_TOP_K=%r is not an integer; using default %d", raw, _TOP_K_DEFAULT)
        return _TOP_K_DEFAULT
    if not (_TOP_K_MIN <= value <= _TOP_K_MAX):
        logger.warning(
            "RAG_TOP_K=%d out of range [%d, %d]; using default %d",
            value, _TOP_K_MIN, _TOP_K_MAX, _TOP_K_DEFAULT,
        )
        return _TOP_K_DEFAULT
    return value


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    doc_name: str
    content: str
    score: float
    metadata: dict[str, Any] | None


class RagRetriever:
    def __init__(self, session: AsyncSession, *, customer_id: uuid.UUID | None = None):
        self.session = session
        self.customer_id = customer_id

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_id: uuid.UUID | None = None,
    ) -> list[RetrievalHit]:
        vector = await embed_one(query)
        k = top_k or _default_top_k()

        # ``cosine_distance`` returns a value in [0, 2]; 1 − that is our score.
        distance = RagDocumentChunk.embedding.cosine_distance(vector)
        stmt = (
            select(
                RagDocumentChunk.id,
                RagDocumentChunk.document_id,
                RagDocumentChunk.doc_name,
                RagDocumentChunk.content,
                RagDocumentChunk.metadata_json,
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(k)
        )
        if self.customer_id is not None:
            stmt = stmt.where(RagDocumentChunk.customer_id == self.customer_id)
        if document_id is not None:
            stmt = stmt.where(RagDocumentChunk.document_id == document_id)

        result = await self.session.execute(stmt)
        hits: list[RetrievalHit] = []
        for row in result.all():
            hits.append(
                RetrievalHit(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    doc_name=row.doc_name,
                    content=row.content,
                    score=max(0.0, 1.0 - float(row.distance)),
                    metadata=row.metadata_json,
                )
            )
        return hits
