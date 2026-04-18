"""Write-path for the vector store (pgvector + SQLAlchemy).

Provides bulk chunk insertion for the ingest endpoint. Reads live in
``retriever.py`` since the similarity query shape is quite different from
the write path.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models.rag_document import RagDocumentChunk


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
    """Insert one row per chunk and return the count.

    Caller handles the enclosing transaction — this function only adds
    rows to ``session``. Embeddings must be the same length as chunks;
    mismatches raise.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
        )
    for idx, (content, vector) in enumerate(zip(chunks, embeddings, strict=True)):
        session.add(
            RagDocumentChunk(
                id=uuid.uuid4(),
                document_id=document_id,
                doc_name=doc_name,
                chunk_index=idx,
                content=content,
                metadata_json=metadata,
                embedding=vector,
                customer_id=customer_id,
                user_id=user_id,
            )
        )
    await session.flush()
    return len(chunks)
