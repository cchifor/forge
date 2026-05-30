"""Regression guards for generated multi-tenant data isolation.

The RAG agent tool and conversation repository must scope every query to the
authenticated tenant (and, where relevant, the authenticated user). A missing
scope is a cross-tenant / cross-user data leak. These guards assert the
template source keeps the scope so it cannot silently regress.

``weld.core.context.get_customer_id`` raises when no tenant is in context
(fail-closed), so routing the RAG tool through it means an unauthenticated
agent call refuses to search rather than returning every tenant's documents.
"""

from __future__ import annotations

from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_RAG_TOOL = (
    _BASE
    / "forge/features/rag/templates/rag_pipeline/python/files/src/app/rag/rag_search_tool.py"
)


def test_rag_search_tool_is_tenant_scoped() -> None:
    src = _RAG_TOOL.read_text(encoding="utf-8")
    # Reads the authenticated tenant from context and scopes the retriever.
    assert "get_customer_id" in src, "rag_search must read the tenant from context"
    assert "RagRetriever(session, customer_id=" in src, (
        "rag_search must bind the retriever to the authenticated customer_id"
    )
    # The leaky un-scoped form must be gone.
    assert "RagRetriever(session)" not in src, (
        "rag_search must not build an un-scoped retriever (cross-tenant leak)"
    )


_CONV_REPO = (
    _BASE
    / "forge/features/conversation/templates/conversation_persistence/python/files/src/app/data/repositories/conversation_repository.py"
)


def test_conversation_repo_is_user_scoped() -> None:
    src = _CONV_REPO.read_text(encoding="utf-8")
    # list_conversations + get_conversation + append_message ownership check +
    # archive must each scope by user_id (within-tenant IDOR guard).
    assert src.count("ConversationModel.user_id == self.user_id") >= 4, (
        "get_conversation / append_message / archive must scope by user_id"
    )
    assert "PermissionDeniedError" in src, (
        "append_message must reject conversations the user does not own"
    )
