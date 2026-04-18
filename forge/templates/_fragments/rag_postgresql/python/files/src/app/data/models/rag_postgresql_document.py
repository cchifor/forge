"""Vector chunks stored in plain PostgreSQL — no pgvector extension required.

Embeddings ride along as JSONB arrays. Similarity is computed server-side
(post-fetch, Python). The tradeoff versus `rag_document_chunks` (which uses
pgvector) is read latency on large corpora; the benefit is portability to
managed Postgres instances that don't expose the `vector` extension.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import JSON_TYPE, Base
from service.repository.mixins import TenantMixin, TimestampMixin, UserOwnedMixin


class RagPgDocumentChunk(Base, TenantMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "rag_pg_document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    doc_name: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    # Embedding vector as a JSONB array of floats. Length consistent per collection
    # but not enforced at the column level (use EMBEDDING_DIM env).
    embedding: Mapped[list[float]] = mapped_column(JSON_TYPE, nullable=False)

    __table_args__ = (
        Index("ix_rag_pg_chunks_document", "document_id"),
        Index("ix_rag_pg_chunks_customer", "customer_id"),
    )
