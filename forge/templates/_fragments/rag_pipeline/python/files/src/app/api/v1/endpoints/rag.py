"""RAG ingest / search REST endpoints.

Uses the existing async session dependency from the base template's IoC
container. ``/ingest`` accepts raw text; ``/ingest-pdf`` accepts a multipart
PDF upload that pymupdf parses into text before chunking.

Not auth-gated by default. Wrap with your auth dependency and populate
``customer_id`` / ``user_id`` from the authenticated principal before
exposing in production — the current form fields exist as a dev override.
"""

from __future__ import annotations

import uuid

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Form, HTTPException, UploadFile, status

from app.core.ioc import PublicUnitOfWork
from app.rag.chunker import chunk_text
from app.rag.embeddings import embed
from app.rag.pdf_parser import extract_text_from_bytes
from app.rag.retriever import RagRetriever
from app.rag.vector_store import store_chunks

router = APIRouter()

_ANON = uuid.UUID("00000000-0000-0000-0000-000000000000")


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
@inject
async def ingest(
    uow: FromDishka[PublicUnitOfWork],
    name: str = Form(..., description="Document name / identifier"),
    content: str = Form(..., description="Raw text to ingest"),
    customer_id: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
) -> dict:
    chunks = chunk_text(content)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content produced zero chunks (too short?)",
        )

    embeddings = await embed(chunks)

    try:
        cid = uuid.UUID(customer_id) if customer_id else _ANON
        uid = uuid.UUID(user_id) if user_id else _ANON
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    document_id = uuid.uuid4()
    async with uow:
        count = await store_chunks(
            session=uow.session,
            document_id=document_id,
            doc_name=name,
            customer_id=cid,
            user_id=uid,
            chunks=chunks,
            embeddings=embeddings,
        )
        await uow.commit()
    return {"document_id": str(document_id), "chunks_created": count}


@router.post("/search")
@inject
async def search(
    uow: FromDishka[PublicUnitOfWork],
    query: str = Form(..., description="Search query"),
    top_k: int = Form(5, ge=1, le=50),
    customer_id: str | None = Form(default=None),
) -> dict:
    try:
        cid = uuid.UUID(customer_id) if customer_id else None
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    async with uow:
        retriever = RagRetriever(uow.session, customer_id=cid)
        hits = await retriever.search(query, top_k=top_k)

    return {
        "results": [
            {
                "chunk_id": str(h.chunk_id),
                "document_id": str(h.document_id),
                "doc_name": h.doc_name,
                "content": h.content,
                "score": h.score,
                "metadata": h.metadata,
            }
            for h in hits
        ]
    }


@router.post("/ingest-pdf", status_code=status.HTTP_201_CREATED)
@inject
async def ingest_pdf(
    uow: FromDishka[PublicUnitOfWork],
    file: UploadFile,
    name: str | None = Form(default=None),
    customer_id: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
) -> dict:
    """Parse a PDF upload, chunk its text, embed, and store."""
    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"expected application/pdf, got {file.content_type}",
        )
    data = await file.read()
    try:
        text = extract_text_from_bytes(data, filename=file.filename)
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(e)) from e
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF yielded no extractable text (scanned PDFs need OCR)",
        )

    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="extracted text produced zero chunks",
        )
    embeddings = await embed(chunks)

    try:
        cid = uuid.UUID(customer_id) if customer_id else _ANON
        uid = uuid.UUID(user_id) if user_id else _ANON
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    document_id = uuid.uuid4()
    async with uow:
        count = await store_chunks(
            session=uow.session,
            document_id=document_id,
            doc_name=name or file.filename or "uploaded.pdf",
            customer_id=cid,
            user_id=uid,
            chunks=chunks,
            embeddings=embeddings,
        )
        await uow.commit()
    return {
        "document_id": str(document_id),
        "chunks_created": count,
        "characters_extracted": len(text),
    }
