"""Reranked search endpoint at /api/v1/rag/rerank-search.

Retrieves `top_k * 5` candidates via the pgvector retriever, reranks with
the configured provider (Cohere by default), then returns `top_k`. When
the reranker is unavailable (no API key, missing deps) the endpoint still
returns useful results — just unreranked.
"""

from __future__ import annotations

import uuid

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Form, HTTPException, status

from app.core.ioc import PublicUnitOfWork
from app.rag.reranker import rerank
from app.rag.retriever import RagRetriever

router = APIRouter()

_OVERSAMPLE = 5  # fetch 5x candidates before reranking


@router.post("/search")
@inject
async def search_rerank(
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
        candidates = await retriever.search(query, top_k=top_k * _OVERSAMPLE)

    reranked = await rerank(query, candidates, top_k=top_k)

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
            for h in reranked
        ],
        "reranked": True,
        "candidates_considered": len(candidates),
    }
