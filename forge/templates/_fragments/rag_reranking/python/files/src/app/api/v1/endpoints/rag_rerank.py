"""Reranked search endpoint at /api/v1/rag/rerank-search.

Retrieves `top_k * 5` candidates via the pgvector retriever, reranks with
the configured provider (Cohere by default), then returns `top_k`. When
the reranker is unavailable (no API key, missing deps) the endpoint still
returns useful results — just unreranked.

Auth-gated via `oauth2_scheme`; tenant identity is derived from
`AuthUnitOfWork`.
"""

from __future__ import annotations

import uuid

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Form, HTTPException, status

from app.core.ioc import AuthUnitOfWork
from app.rag.reranker import rerank
from app.rag.retriever import RagRetriever
from service.security.auth import oauth2_scheme

router = APIRouter(dependencies=[Depends(oauth2_scheme)])

_OVERSAMPLE = 5


def _customer_id(uow: AuthUnitOfWork) -> uuid.UUID:
    account = uow._account
    if account is None or account.customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated tenant required for RAG operations",
        )
    return account.customer_id


@router.post("/search")
@inject
async def search_rerank(
    uow: FromDishka[AuthUnitOfWork],
    query: str = Form(..., description="Search query"),
    top_k: int = Form(5, ge=1, le=50),
) -> dict:
    cid = _customer_id(uow)

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
