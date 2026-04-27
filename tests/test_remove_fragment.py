"""Tests for ``forge --remove-fragment NAME`` (P1.2, 1.1.0-alpha.2)."""

from __future__ import annotations

from forge.cli.commands.remove_fragment import _options_that_enable
from forge.options import OPTION_REGISTRY


class TestOptionsThatEnable:
    """Lookup helper — find every option whose ``enables`` map references
    a given fragment."""

    def test_finds_single_enabling_option(self) -> None:
        # ``rate_limit`` fragment is enabled exactly by middleware.rate_limit.
        result = _options_that_enable("rate_limit", OPTION_REGISTRY)
        paths = [path for path, _opt, _val in result]
        assert "middleware.rate_limit" in paths

    def test_finds_zero_for_unknown_fragment(self) -> None:
        result = _options_that_enable("not_a_real_fragment", OPTION_REGISTRY)
        assert result == []

    def test_finds_multiple_for_shared_dep(self) -> None:
        # ``conversation_persistence`` is enabled by conversation.persistence
        # AND every rag.backend != none AND chat.attachments. We don't
        # assert a specific count — only that more than one option enables it,
        # which is the trigger for --remove-fragment's "ambiguous" error.
        result = _options_that_enable("conversation_persistence", OPTION_REGISTRY)
        assert len(result) >= 2

    def test_returns_value_that_enables(self) -> None:
        # ``rag_pipeline`` is enabled when ``rag.backend`` != none.
        # We expect the result tuple's third element to capture the value
        # that enables (one of the rag.backend ENUM values).
        result = _options_that_enable("rag_pipeline", OPTION_REGISTRY)
        rag_paths = [
            (path, val) for path, _opt, val in result if path == "rag.backend"
        ]
        assert rag_paths
        # Value should be a non-default option of rag.backend.
        path, value = rag_paths[0]
        assert value in (
            "pgvector",
            "qdrant",
            "chroma",
            "milvus",
            "weaviate",
            "pinecone",
            "postgresql",
        )
