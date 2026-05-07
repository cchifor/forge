"""Taskiq tasks for asynchronous RAG ingestion.

Offloads the embed + store path (which is I/O-bound on the OpenAI API call)
from the request thread to the worker. Enqueue from any handler:

    from app.worker.rag_tasks import ingest_text_task
    task = await ingest_text_task.kiq(name="README", content=body)
    # task.task_id  - return immediately; let the worker embed + store

Requires `rag_pipeline` and `background_tasks` features enabled. The
dispatch picks the DATABASE_URL-bound engine on first call rather than
relying on the request scope's Dishka session (tasks run outside any
request).
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.rag.chunker import chunk_text
from app.rag.embeddings import embed
from app.rag.vector_store import store_chunks
from app.worker.broker import broker

_ANON = uuid.UUID("00000000-0000-0000-0000-000000000000")

_session_factory = None


def _get_session_factory():
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be set for rag_sync_tasks")
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    _session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return _session_factory


@broker.task
async def ingest_text_task(
    *,
    name: str,
    content: str,
    customer_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Chunk, embed, and store a plain-text document in pgvector."""
    chunks = chunk_text(content)
    if not chunks:
        return {"document_id": None, "chunks_created": 0, "status": "empty"}

    embeddings = await embed(chunks)
    cid = uuid.UUID(customer_id) if customer_id else _ANON
    uid = uuid.UUID(user_id) if user_id else _ANON
    document_id = uuid.uuid4()

    factory = _get_session_factory()
    async with factory() as session:
        count = await store_chunks(
            session=session,
            document_id=document_id,
            doc_name=name,
            customer_id=cid,
            user_id=uid,
            chunks=chunks,
            embeddings=embeddings,
        )
        await session.commit()

    return {
        "document_id": str(document_id),
        "chunks_created": count,
        "status": "ok",
    }


@broker.task
async def ingest_pdf_bytes_task(
    *,
    name: str,
    data: bytes,
    customer_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Parse PDF bytes and ingest — use when you've already uploaded to
    storage and want to queue the embed step separately from the upload
    request."""
    from app.rag.pdf_parser import extract_text_from_bytes

    text = extract_text_from_bytes(data, filename=name)
    if not text.strip():
        return {"document_id": None, "chunks_created": 0, "status": "no_text"}

    return await ingest_text_task(
        name=name,
        content=text,
        customer_id=customer_id,
        user_id=user_id,
    )
