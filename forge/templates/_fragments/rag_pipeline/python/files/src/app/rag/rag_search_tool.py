"""``rag_search`` — exposes the vector store to the LLM agent.

Registers itself into the process-wide ``ToolRegistry`` at import time so
an enabled ``agent_tools`` feature + an enabled ``rag_pipeline`` → the
LLM can call RAG automatically. If either dependency is missing, import
still succeeds but the tool just isn't registered.

Tools run *outside* a normal request's Dishka scope (they're invoked from
the agent loop), so we open a short-lived session from the db module's
session factory. This is fine for read-only retrieval — one connection
per call is cheap compared to embedding + RTT to the LLM.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_session_factory = None


def _get_session_factory():
    """Return a process-wide async session factory bound to ``DATABASE_URL``.

    Tool invocations happen outside the Dishka request scope, so we build
    our own engine. The engine is reused across calls; cost is a one-time
    connection pool init.
    """
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    import os

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "rag_search tool requires DATABASE_URL env var to connect to pgvector"
        )
    # Translate a psycopg-style URL to asyncpg if needed.
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    _session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return _session_factory


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


def _try_register() -> None:
    try:
        from app.agents.tool import Tool, tool_registry  # type: ignore
    except ImportError:
        # agent_tools not enabled — skip quietly. RAG still works via REST.
        return

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
    if tool.name not in tool_registry:
        tool_registry.register(tool)


_try_register()
