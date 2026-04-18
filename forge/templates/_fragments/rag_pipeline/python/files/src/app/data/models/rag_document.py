"""RAG document chunk model — pgvector-backed semantic search.

Each row is one chunk (not a whole document). The source document's
identity (filename, path, hash) lives on the ``document_id`` + ``doc_name``
denormalized fields so search results can cite without a second query.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import JSON_TYPE, Base
from service.repository.mixins import TenantMixin, TimestampMixin, UserOwnedMixin


EMBEDDING_DIM = 1536  # matches text-embedding-3-small; override in env for other models


class RagDocumentChunk(Base, TenantMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "rag_document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    doc_name: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form: source URL, page number, section, etc. Kept on the chunk so
    # filters can run without a join.
    metadata_json: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    __table_args__ = (
        Index("ix_rag_chunks_document", "document_id"),
        Index("ix_rag_chunks_customer", "customer_id"),
        # HNSW index for approximate nearest-neighbor. Created by migration.
    )
