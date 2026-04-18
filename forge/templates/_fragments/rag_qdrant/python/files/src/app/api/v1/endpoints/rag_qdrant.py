"""Qdrant-backed RAG endpoints — parallel to the pgvector /rag path.

Lives under /api/v1/rag/qdrant so both backends can coexist in the same
service. Promote this to the primary /api/v1/rag path by routing there
instead of /rag/qdrant when you're ready to drop pgvector.

Auth-gated via `oauth2_scheme`; tenant identity is derived from the
authenticated `User` injected by Dishka — callers cannot act against
another tenant's corpus.
"""

from __future__ import annotations

import uuid

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from app.rag import qdrant_backend
from app.rag.chunker import chunk_text
from app.rag.embeddings import embed, embed_one
from app.rag.pdf_parser import extract_text_from_bytes
from service.domain.user import User
from service.security.auth import oauth2_scheme

router = APIRouter(dependencies=[Depends(oauth2_scheme)])


def _tenant_ids(user: User) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        return uuid.UUID(user.customer_id), uuid.UUID(user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid tenant identity on authenticated principal: {e}",
        ) from e


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
@inject
async def ingest(
    user: FromDishka[User],
    name: str = Form(..., description="Document name / identifier"),
    content: str = Form(..., description="Raw text to ingest"),
) -> dict:
    cid, uid = _tenant_ids(user)
    chunks = chunk_text(content)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content produced zero chunks (too short?)",
        )
    embeddings = await embed(chunks)

    document_id = uuid.uuid4()
    count = await qdrant_backend.store_chunks(
        document_id=document_id,
        doc_name=name,
        customer_id=cid,
        user_id=uid,
        chunks=chunks,
        embeddings=embeddings,
    )
    return {"document_id": str(document_id), "chunks_created": count, "backend": "qdrant"}


@router.post("/ingest-pdf", status_code=status.HTTP_201_CREATED)
@inject
async def ingest_pdf(
    user: FromDishka[User],
    file: UploadFile,
    name: str | None = Form(default=None),
) -> dict:
    cid, uid = _tenant_ids(user)
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

    document_id = uuid.uuid4()
    count = await qdrant_backend.store_chunks(
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
        "backend": "qdrant",
    }


@router.post("/search")
@inject
async def search(
    user: FromDishka[User],
    query: str = Form(..., description="Search query"),
    top_k: int = Form(5, ge=1, le=50),
) -> dict:
    cid, _ = _tenant_ids(user)

    vector = await embed_one(query)
    hits = await qdrant_backend.search(vector, top_k=top_k, customer_id=cid)
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
        "backend": "qdrant",
    }
