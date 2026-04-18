"""Optional rerank step after initial retrieval.

The first-pass retriever (pgvector, Qdrant, Chroma) trades precision for
latency — HNSW returns approximate nearest neighbors. A rerank pass over
the top-N (e.g. 25) then re-sorting to return the real top-k (e.g. 5)
materially improves result quality for agent-grade RAG.

Providers:
  - ``cohere`` (default) — hosted, uses the ``rerank-v3.5`` model. Requires
    ``COHERE_API_KEY``.
  - ``local`` — sentence-transformers cross-encoder run in-process.
    Requires ``pip install sentence-transformers`` (heavy: pulls torch).

Without a configured provider, :func:`rerank` is a pass-through no-op.
Callers can always invoke it safely.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

logger = logging.getLogger(__name__)


class _Scorable(Protocol):
    content: str
    score: float


HitT = TypeVar("HitT", bound=_Scorable)


@dataclass(frozen=True)
class RerankedHit:
    """Lightweight wrapper tracking the rerank score alongside the original."""

    original: object  # the source hit (PgvectorHit | QdrantHit | ChromaHit | ...)
    rerank_score: float


def _provider() -> str:
    return os.environ.get("RERANKER_PROVIDER", "cohere").strip().lower()


def _model() -> str:
    return os.environ.get(
        "RERANKER_MODEL",
        "rerank-v3.5" if _provider() == "cohere" else "cross-encoder/ms-marco-MiniLM-L-6-v2",
    )


async def rerank(
    query: str, hits: Sequence[HitT], *, top_k: int | None = None
) -> list[HitT]:
    """Reorder ``hits`` by the configured reranker and return the top-k.

    If the provider isn't configured (missing API key / missing local deps),
    returns ``hits[:top_k]`` unchanged so callers never have to handle
    "rerank unavailable" as a branch.
    """
    if not hits:
        return list(hits)
    limit = top_k if top_k is not None else len(hits)
    prov = _provider()

    try:
        if prov == "cohere":
            scored = await _rerank_cohere(query, hits)
        elif prov == "local":
            scored = _rerank_local(query, hits)
        else:
            logger.warning("RERANKER_PROVIDER=%r unrecognized; skipping rerank", prov)
            return list(hits[:limit])
    except Exception as e:  # noqa: BLE001
        logger.warning("rerank failed (%s); returning original order", e)
        return list(hits[:limit])

    # Sort by rerank score (higher is better) and return the top-k originals.
    scored.sort(key=lambda x: x[1], reverse=True)
    return [h for h, _ in scored[:limit]]


async def _rerank_cohere(query: str, hits: Sequence[HitT]) -> list[tuple[HitT, float]]:
    api_key = os.environ.get("COHERE_API_KEY")
    if not api_key:
        raise RuntimeError("COHERE_API_KEY not set")

    try:
        import cohere  # type: ignore
    except ImportError as e:
        raise RuntimeError("cohere package not installed") from e

    client = cohere.AsyncClientV2(api_key=api_key)
    documents = [h.content for h in hits]
    response = await client.rerank(
        model=_model(),
        query=query,
        documents=documents,
        top_n=len(documents),
    )
    scored: list[tuple[HitT, float]] = []
    for result in response.results:
        idx = result.index
        if 0 <= idx < len(hits):
            scored.append((hits[idx], float(result.relevance_score)))
    return scored


def _rerank_local(query: str, hits: Sequence[HitT]) -> list[tuple[HitT, float]]:
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except ImportError as e:
        raise RuntimeError("sentence-transformers not installed") from e

    encoder = CrossEncoder(_model())
    pairs = [(query, h.content) for h in hits]
    scores = encoder.predict(pairs)
    return list(zip(hits, (float(s) for s in scores), strict=True))
