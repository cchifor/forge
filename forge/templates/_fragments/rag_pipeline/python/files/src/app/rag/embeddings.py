"""OpenAI embeddings client.

Deliberately single-provider in v1 — OpenAI's ``text-embedding-3-small``
has broad support and matches pgvector's 1536-dim default. Swap to a
different provider by pointing ``OPENAI_BASE_URL`` at an OpenAI-compatible
endpoint (e.g., Voyage via proxy) and updating ``EMBEDDING_MODEL``.

Requests are async and batched — the OpenAI embeddings API accepts arrays
of up to 2048 inputs per call, so chunking a large document produces one
request, not one-per-chunk.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

logger = logging.getLogger(__name__)


def embedding_dim() -> int:
    try:
        return int(os.environ.get("EMBEDDING_DIM", "1536"))
    except ValueError:
        return 1536


def _model() -> str:
    return os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")


_client = None


def _get_client():
    """Lazy-init the OpenAI async client so importing this module doesn't
    crash on services that don't actually use RAG."""
    global _client
    if _client is None:
        from openai import AsyncOpenAI  # type: ignore

        kwargs: dict = {"api_key": os.environ.get("OPENAI_API_KEY", "")}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        _client = AsyncOpenAI(**kwargs)
    return _client


async def embed(texts: Sequence[str]) -> list[list[float]]:
    """Return one embedding vector per input text.

    Empty input list returns an empty list without hitting the API.
    """
    inputs = [t for t in texts if t]
    if not inputs:
        return []
    client = _get_client()
    resp = await client.embeddings.create(model=_model(), input=list(inputs))
    return [item.embedding for item in resp.data]


async def embed_one(text: str) -> list[float]:
    vectors = await embed([text])
    if not vectors:
        raise ValueError("empty text cannot be embedded")
    return vectors[0]


def reset_client() -> None:
    """Test hook; resets the module-level client singleton."""
    global _client
    _client = None
