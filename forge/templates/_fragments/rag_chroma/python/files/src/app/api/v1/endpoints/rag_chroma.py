"""Chroma-backed RAG endpoints under /api/v1/rag/chroma.

Same shape as rag_qdrant's endpoints so clients can swap backends by
changing the path prefix. Uses the chunker + embeddings + pdf_parser from
rag_pipeline.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, HTTPException, UploadFile, status

from app.rag import chroma_backend
from app.rag.chunker import chunk_text
from app.rag.embeddings import embed, embed_one
from app.rag.pdf_parser import extract_text_from_bytes

router = APIRouter()

_ANON = uuid.UUID("00000000-0000-0000-0000-000000000000")


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest(
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
    count = await chroma_backend.store_chunks(
        document_id=document_id,
        doc_name=name,
        customer_id=cid,
        user_id=uid,
        chunks=chunks,
        embeddings=embeddings,
    )
    return {"document_id": str(document_id), "chunks_created": count, "backend": "chroma"}


@router.post("/ingest-pdf", status_code=status.HTTP_201_CREATED)
async def ingest_pdf(
    file: UploadFile,
    name: str | None = Form(default=None),
    customer_id: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
) -> dict:
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
            detail="PDF yielded no extractable text",
        )
    chunks = chunk_text(text)
    embeddings = await embed(chunks)

    try:
        cid = uuid.UUID(customer_id) if customer_id else _ANON
        uid = uuid.UUID(user_id) if user_id else _ANON
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    document_id = uuid.uuid4()
    count = await chroma_backend.store_chunks(
        document_id=document_id,
        doc_name=name or file.filename or "uploaded.pdf",
        customer_id=cid,
        user_id=uid,
        chunks=chunks,
        embeddings=embeddings,
    )
    return {
        "document_id": str(document_id),
        "chunks_created": count,
        "characters_extracted": len(text),
        "backend": "chroma",
    }


@router.post("/search")
async def search(
    query: str = Form(..., description="Search query"),
    top_k: int = Form(5, ge=1, le=50),
    customer_id: str | None = Form(default=None),
) -> dict:
    try:
        cid = uuid.UUID(customer_id) if customer_id else None
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    vector = await embed_one(query)
    hits = await chroma_backend.search(vector, top_k=top_k, customer_id=cid)
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
        ],
        "backend": "chroma",
    }
