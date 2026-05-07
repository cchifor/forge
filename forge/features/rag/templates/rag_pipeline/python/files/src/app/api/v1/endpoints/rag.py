"""RAG ingest / search REST endpoints.

Auth-gated via the same `oauth2_scheme` router dependency as the rest of
`/api/v1`. Tenant identity is derived from the authenticated principal
via `FromDishka[AuthUnitOfWork]` — endpoints cannot be called against
another tenant's corpus.
"""

from __future__ import annotations

import uuid

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from app.core.ioc import AuthUnitOfWork
from app.rag.chunker import chunk_text
from app.rag.embeddings import embed
from app.rag.pdf_parser import extract_text_from_bytes
from app.rag.retriever import RagRetriever
from app.rag.vector_store import store_chunks
from service.security.auth import oauth2_scheme

router = APIRouter(dependencies=[Depends(oauth2_scheme)])


def _tenant_ids(uow: AuthUnitOfWork) -> tuple[uuid.UUID, uuid.UUID]:
    account = uow._account
    if account is None or account.customer_id is None or account.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated tenant required for RAG operations",
        )
    return account.customer_id, account.user_id


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
@inject
async def ingest(
    uow: FromDishka[AuthUnitOfWork],
    name: str = Form(..., description="Document name / identifier"),
    content: str = Form(..., description="Raw text to ingest"),
) -> dict:
    cid, uid = _tenant_ids(uow)
    chunks = chunk_text(content)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content produced zero chunks (too short?)",
        )

    embeddings = await embed(chunks)

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
    uow: FromDishka[AuthUnitOfWork],
    query: str = Form(..., description="Search query"),
    top_k: int = Form(5, ge=1, le=50),
) -> dict:
    cid, _ = _tenant_ids(uow)

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
    uow: FromDishka[AuthUnitOfWork],
    file: UploadFile,
    name: str | None = Form(default=None),
) -> dict:
    """Parse a PDF upload, chunk its text, embed, and store."""
    cid, uid = _tenant_ids(uow)
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
