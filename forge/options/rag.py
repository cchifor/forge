"""``rag.*`` — knowledge / retrieval-augmented generation stack."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="rag.backend",
        type=OptionType.ENUM,
        default="none",
        options=(
            "none",
            "pgvector",
            "qdrant",
            "chroma",
            "milvus",
            "weaviate",
            "pinecone",
            "postgresql",
        ),
        summary="Select the vector-store backend for RAG ingest + search.",
        description="""\
Picks which vector store the generated service talks to. ``none`` skips
the RAG stack entirely. ``pgvector`` uses the default Postgres
extension. All other values swap in an alternative backend alongside
the shared chunker + embeddings + PDF-parser modules.

OPTIONS: none | pgvector | qdrant | chroma | milvus | weaviate | pinecone | postgresql""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
        # conversation_persistence is a transitive dep of rag_pipeline;
        # bundling it means a single `rag.backend=<x>` spin is
        # self-contained (the resolver won't error on a missing dep).
        # 1.0.0a2: rag.backend now drives the port+adapter pattern
        # (ADR-002). The vector_store_port fragment is always applied
        # alongside the chosen adapter, so a generated project can swap
        # providers via env config without regeneration. Legacy rag_*
        # fragments are deprecated but still resolvable for
        # pre-1.0.0a2 projects invoking `forge --update`.
        enables={
            "pgvector": (
                "conversation_persistence",
                "rag_pipeline",
                "vector_store_port",
                "vector_store_postgres",
            ),
            "qdrant": (
                "conversation_persistence",
                "rag_pipeline",
                "vector_store_port",
                "vector_store_qdrant",
            ),
            "chroma": (
                "conversation_persistence",
                "rag_pipeline",
                "vector_store_port",
                "vector_store_chroma",
            ),
            "milvus": (
                "conversation_persistence",
                "rag_pipeline",
                "vector_store_port",
                "vector_store_milvus",
            ),
            "weaviate": (
                "conversation_persistence",
                "rag_pipeline",
                "vector_store_port",
                "vector_store_weaviate",
            ),
            "pinecone": (
                "conversation_persistence",
                "rag_pipeline",
                "vector_store_port",
                "vector_store_pinecone",
            ),
            "postgresql": (
                "conversation_persistence",
                "rag_pipeline",
                "vector_store_port",
                "vector_store_postgres",
            ),
        },
    )
)


register_option(
    Option(
        path="rag.embeddings",
        type=OptionType.ENUM,
        default="openai",
        options=("openai", "voyage"),
        summary="Embeddings provider for RAG ingest + query.",
        description="""\
OpenAI's text-embedding-3-small (1536-dim) is the default. Voyage AI
offers domain-specialized models (voyage-3.5, voyage-code-3,
voyage-finance-2) that typically score higher on retrieval benchmarks
— at the cost of a separate API key and incompatible vector shapes
(rebuild the index after switching).

Only meaningful when ``rag.backend ≠ none``.

OPTIONS: openai | voyage""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
        enables={"voyage": ("rag_embeddings_voyage",)},
    )
)


register_option(
    Option(
        path="rag.reranker",
        type=OptionType.BOOL,
        default=False,
        summary="Cohere rerank (+ local cross-encoder fallback) for sharper top-K.",
        description="""\
Post-retrieval rerank pass. Oversamples candidates from the vector
store and reorders them with a cross-encoder so top-K is sharper than
pure embedding similarity gives you. Cohere is the default provider; a
local sentence-transformers cross-encoder is available as an opt-in
fallback. Degrades to a silent no-op when no provider is configured.

BACKENDS: python
ENDPOINTS: /api/v1/rag/rerank/search
REQUIRES: rag.backend ≠ none; COHERE_API_KEY.""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
        enables={True: ("rag_reranking",)},
    )
)


register_option(
    Option(
        path="rag.top_k",
        type=OptionType.INT,
        default=5,
        min=1,
        max=100,
        summary="Default number of chunks returned per RAG query.",
        description="""\
Number of top-K chunks the RAG retriever returns by default. Only
meaningful when ``rag.backend ≠ none``. Callers can still override
per-query via the top_k parameter on /api/v1/rag/search.

Used as the default for every rag_* endpoint and the `rag_search` agent
tool. Written into .env.example as RAG_TOP_K.""",
        category=FeatureCategory.KNOWLEDGE,
        stability="experimental",
    )
)
