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
import threading
from collections.abc import Sequence

logger = logging.getLogger(__name__)


_EMBEDDING_DIM_MIN = 32
_EMBEDDING_DIM_MAX = 8192
_EMBEDDING_DIM_DEFAULT = 1536


def embedding_dim() -> int:
    """Return the embedding vector dimensionality from ``EMBEDDING_DIM``.

    Clamped to [32, 8192]. An invalid or out-of-range value logs a
    warning and falls back to 1536 (OpenAI text-embedding-3-small's
    default) rather than silently accepting a mismatch with the pgvector
    column type — which would raise cryptic SQL errors at insert time.
    """
    raw = os.environ.get("EMBEDDING_DIM")
    if raw is None:
        return _EMBEDDING_DIM_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "EMBEDDING_DIM=%r is not an integer; using default %d",
            raw,
            _EMBEDDING_DIM_DEFAULT,
        )
        return _EMBEDDING_DIM_DEFAULT
    if not (_EMBEDDING_DIM_MIN <= value <= _EMBEDDING_DIM_MAX):
        logger.warning(
            "EMBEDDING_DIM=%d out of range [%d, %d]; using default %d",
            value,
            _EMBEDDING_DIM_MIN,
            _EMBEDDING_DIM_MAX,
            _EMBEDDING_DIM_DEFAULT,
        )
        return _EMBEDDING_DIM_DEFAULT
    return value


def _model() -> str:
    return os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")


_client = None
_client_lock = threading.Lock()


def _get_client():
    """Thread-safe singleton OpenAI async client (double-checked lock).

    Built lazily so importing this module doesn't crash on services that
    don't actually use RAG. Serializes construction across threads so a
    burst of startup traffic can't create N clients with N connection
    pools — one process, one client.
    """
    global _client
    if _client is None:
        with _client_lock:
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
    """Test hook; clears the singleton so the next call re-reads env vars."""
    global _client
    with _client_lock:
        _client = None
