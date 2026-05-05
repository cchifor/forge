"""Vector store port + adapters (1.0.0a2+).

Reference implementation of ADR-002 (ports + adapters). The
``vector_store_port`` fragment ships the abstract interface; each
``vector_store_<backend>`` fragment plugs a concrete impl in. This is
the preferred shape over the legacy ``rag_<backend>`` fragments which
inline the backend choice — plugin-authored backends should follow
this pattern.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="vector_store_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="vector_store_port/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="vector_store_qdrant",
        depends_on=("vector_store_port",),
        capabilities=("qdrant",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_qdrant/python",
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


register_fragment(
    Fragment(
        name="vector_store_chroma",
        depends_on=("vector_store_port",),
        capabilities=("chroma",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_chroma/python",
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
        name="vector_store_pinecone",
        depends_on=("vector_store_port",),
        capabilities=("pinecone",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_pinecone/python",
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
        name="vector_store_milvus",
        depends_on=("vector_store_port",),
        capabilities=("milvus",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_milvus/python",
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
        name="vector_store_weaviate",
        depends_on=("vector_store_port",),
        capabilities=("weaviate",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_weaviate/python",
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
        name="vector_store_postgres",
        depends_on=("vector_store_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_postgres/python",
            ),
        },
    )
)
