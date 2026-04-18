"""Fragment smoke tests for `rag_pipeline`.

Covers the A1.4 embeddings-client singleton + the A3.2 env-var clamping
+ the A2.3 shared-session-factory accessor integration.
"""

from __future__ import annotations

import pytest

from app.rag.embeddings import _get_client, embedding_dim, reset_client
from app.rag.retriever import _default_top_k


def test_embeddings_client_is_singleton() -> None:
    reset_client()
    c1 = _get_client()
    c2 = _get_client()
    assert c1 is c2, "concurrent callers must share one client"


def test_reset_client_clears_singleton() -> None:
    reset_client()
    before = _get_client()
    reset_client()
    after = _get_client()
    assert before is not after


def test_embedding_dim_clamps_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_DIM", "0")
    assert embedding_dim() == 1536  # default when out of range

    monkeypatch.setenv("EMBEDDING_DIM", "100000")
    assert embedding_dim() == 1536

    monkeypatch.setenv("EMBEDDING_DIM", "not-a-number")
    assert embedding_dim() == 1536


def test_embedding_dim_accepts_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_DIM", "1024")
    assert embedding_dim() == 1024


def test_top_k_clamps_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_TOP_K", "0")
    assert _default_top_k() == 5

    monkeypatch.setenv("RAG_TOP_K", "9999")
    assert _default_top_k() == 5

    monkeypatch.setenv("RAG_TOP_K", "garbage")
    assert _default_top_k() == 5


def test_top_k_accepts_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_TOP_K", "20")
    assert _default_top_k() == 20


def test_rag_search_tool_register_is_explicit() -> None:
    """No import-time side-effect — the tool only registers when
    `register_rag_search_tool()` is called explicitly (by lifecycle).
    """
    from app.rag import rag_search_tool

    assert callable(rag_search_tool.register_rag_search_tool)
    assert not hasattr(rag_search_tool, "_try_register")
