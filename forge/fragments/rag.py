"""RAG (retrieval-augmented generation) fragments — pipeline + backends.

``rag_pipeline`` is the canonical entry point: it ships the embedding
loop, document ingestion, and pgvector default. The other fragments
attach: embedding-provider variants (Voyage), reranker (Cohere), and
vector-store back-ends (Milvus, Weaviate, Pinecone, Chroma, Postgres,
Qdrant). ``rag_sync_tasks`` adds background syncing via
``background_tasks``.

The legacy ``rag_*`` direct-backend fragments coexist with the newer
``vector_store_*`` port+adapter fragments — see RFC-005. The newer
shape is preferred for plugin-authored backends.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="rag_pipeline",
        depends_on=("conversation_persistence",),
        capabilities=("postgres-pgvector",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_pipeline/python",
                dependencies=(
                    "pgvector>=0.3.0",
                    "openai>=2.0.0",
                    "pymupdf>=1.24.0",
                    "python-multipart>=0.0.20",
                ),
                env_vars=(
                    ("EMBEDDING_MODEL", "text-embedding-3-small"),
                    ("EMBEDDING_DIM", "1536"),
                    ("RAG_TOP_K", "5"),
                    ("OPENAI_BASE_URL", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_sync_tasks",
        depends_on=("rag_pipeline", "background_tasks"),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="rag_sync_tasks/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_embeddings_voyage",
        depends_on=("rag_pipeline",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_embeddings_voyage/python",
                dependencies=("voyageai>=0.3.0",),
                env_vars=(
                    ("VOYAGE_API_KEY", ""),
                    ("EMBEDDING_MODEL", "voyage-3.5"),
                    ("EMBEDDING_DIM", "1024"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_reranking",
        depends_on=("rag_pipeline",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_reranking/python",
                dependencies=("cohere>=5.13.0",),
                env_vars=(
                    ("COHERE_API_KEY", ""),
                    ("RERANKER_PROVIDER", "cohere"),
                    ("RERANKER_MODEL", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_milvus",
        depends_on=("rag_pipeline",),
        capabilities=("milvus",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_milvus/python",
                dependencies=("pymilvus>=2.5.0",),
                env_vars=(
                    ("MILVUS_URI", "http://milvus:19530"),
                    ("MILVUS_TOKEN", ""),
                    ("MILVUS_COLLECTION", "forge_rag"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_weaviate",
        depends_on=("rag_pipeline",),
        capabilities=("weaviate",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_weaviate/python",
                dependencies=("weaviate-client>=4.9.0",),
                env_vars=(
                    ("WEAVIATE_URL", "http://weaviate:8080"),
                    ("WEAVIATE_API_KEY", ""),
                    ("WEAVIATE_COLLECTION", "ForgeRag"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_pinecone",
        depends_on=("rag_pipeline",),
        capabilities=("pinecone",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_pinecone/python",
                dependencies=("pinecone>=5.4.0",),
                env_vars=(
                    ("PINECONE_API_KEY", ""),
                    ("PINECONE_INDEX", "forge-rag"),
                    ("PINECONE_ENVIRONMENT", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_chroma",
        depends_on=("rag_pipeline",),
        capabilities=("chroma",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_chroma/python",
                dependencies=("chromadb>=0.5.0",),
                env_vars=(
                    ("CHROMA_URL", "http://chroma:8000"),
                    ("CHROMA_COLLECTION", "forge_rag"),
                    ("CHROMA_TENANT", "default_tenant"),
                    ("CHROMA_DATABASE", "default_database"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_postgresql",
        depends_on=("rag_pipeline",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="rag_postgresql/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_qdrant",
        depends_on=("rag_pipeline",),
        capabilities=("qdrant",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_qdrant/python",
                dependencies=("qdrant-client>=1.12.0",),
                env_vars=(
                    ("QDRANT_URL", "http://qdrant:6333"),
                    ("QDRANT_API_KEY", ""),
                    ("QDRANT_COLLECTION", "forge_rag"),
                ),
            ),
        },
    )
)
