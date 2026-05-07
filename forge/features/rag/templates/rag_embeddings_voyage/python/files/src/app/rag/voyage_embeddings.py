"""Voyage AI embeddings provider.

Drop-in replacement for :mod:`app.rag.embeddings` when ``VOYAGE_API_KEY``
is set. Voyage typically outperforms OpenAI's ``text-embedding-3-small``
on retrieval benchmarks and ships domain-specialized models
(``voyage-finance-2``, ``voyage-code-3``, etc.) worth considering for
vertical applications.

Switching in:

    # BEFORE
    from app.rag.embeddings import embed, embed_one

    # AFTER
    from app.rag.voyage_embeddings import embed, embed_one

The ``Voyage`` embedding dimension varies by model (``voyage-3.5`` is 1024,
``voyage-3.5-lite`` is 1024, ``voyage-code-3`` is 1024). Set
``EMBEDDING_DIM`` to match; **you must rebuild any existing vector
collection since embeddings from different providers are not comparable**.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

logger = logging.getLogger(__name__)


def embedding_dim() -> int:
    try:
        return int(os.environ.get("EMBEDDING_DIM", "1024"))
    except ValueError:
        return 1024


def _model() -> str:
    return os.environ.get("EMBEDDING_MODEL", "voyage-3.5")


def _input_type(is_query: bool) -> str:
    """Voyage supports asymmetric embeddings — query vs. document."""
    return "query" if is_query else "document"


_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    import voyageai  # type: ignore

    api_key = os.environ.get("VOYAGE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY not set — either set it or switch back to "
            "app.rag.embeddings (OpenAI)"
        )
    _client = voyageai.AsyncClient(api_key=api_key)
    return _client


async def embed(texts: Sequence[str], *, is_query: bool = False) -> list[list[float]]:
    """Embed a batch of texts. Pass ``is_query=True`` when embedding a
    search query so Voyage uses the query-optimized path."""
    inputs = [t for t in texts if t]
    if not inputs:
        return []
    client = _get_client()
    resp = await client.embed(
        texts=list(inputs),
        model=_model(),
        input_type=_input_type(is_query),
    )
    return list(resp.embeddings)


async def embed_one(text: str, *, is_query: bool = True) -> list[float]:
    """Convenience for single-query embedding — defaults to query mode
    which is what retrievers want."""
    vectors = await embed([text], is_query=is_query)
    if not vectors:
        raise ValueError("empty text cannot be embedded")
    return vectors[0]


def reset_client() -> None:
    """Test hook; resets the module-level client singleton."""
    global _client
    _client = None
