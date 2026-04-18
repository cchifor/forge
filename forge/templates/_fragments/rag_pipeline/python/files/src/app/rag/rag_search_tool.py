"""``rag_search`` — exposes the vector store to the LLM agent.

Registers itself into the process-wide ``ToolRegistry`` at import time so
an enabled ``agent_tools`` feature + an enabled ``rag_pipeline`` → the
LLM can call RAG automatically. If either dependency is missing, import
still succeeds but the tool just isn't registered.

Tools run *outside* a normal request's Dishka scope (they're invoked from
the agent loop), so we read the session factory from ``app.core.db`` —
the module where ``AppLifecycle._on_startup`` publishes the container-
built factory. One engine, one pool, shared with every request and every
other tool / worker.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_session_factory():
    """Return the shared async session factory.

    Falls back to constructing a standalone factory when the app hasn't
    been bootstrapped (e.g., unit tests that exercise the tool without
    spinning up the FastAPI lifecycle). The fallback still uses
    ``DATABASE_URL`` for configuration.
    """
    from app.core.db import get_session_factory

    try:
        return get_session_factory()
    except RuntimeError:
        pass

    # Fallback: lifecycle hasn't published yet. Build one locally so that
    # standalone test / CLI runs keep working. Production traffic never
    # hits this branch because lifecycle publishes before anything else.
    import os

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "rag_search tool requires DATABASE_URL env var to connect to pgvector"
        )
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def _rag_search(query: str, top_k: int = 5) -> dict:
    """Semantic search over ingested RAG chunks. Returns the top matches
    ordered by cosine similarity."""
    from app.rag.retriever import RagRetriever

    factory = _get_session_factory()
    async with factory() as session:
        retriever = RagRetriever(session)
        hits = await retriever.search(query, top_k=top_k)
    return {
        "query": query,
        "results": [
            {
                "doc_name": h.doc_name,
                "content": h.content,
                "score": h.score,
            }
            for h in hits
        ],
    }


def register_rag_search_tool() -> bool:
    """Register the ``rag_search`` agent tool.

    Explicit (no import-time side-effect) so unit tests that import this
    module don't mutate the shared ``ToolRegistry``. Called from
    ``AppLifecycle._on_startup`` via the fragment's inject.yaml; a
    no-op return value is ``False`` if ``agent_tools`` isn't enabled
    (RAG still works through the REST endpoints either way).
    """
    try:
        from app.agents.tool import Tool, tool_registry  # type: ignore
    except ImportError:
        # agent_tools not enabled — skip quietly.
        return False

    tool = Tool(
        name="rag_search",
        description=(
            "Search the knowledge base for text relevant to a query. "
            "Returns the top matching chunks with their document names and "
            "similarity scores. Use this when the user asks a factual question "
            "that the knowledge base is likely to contain."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "top_k": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_rag_search,
        tags=("rag", "search"),
    )
    if tool.name in tool_registry:
        return False
    tool_registry.register(tool)
    return True
