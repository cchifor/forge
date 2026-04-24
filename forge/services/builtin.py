"""Built-in service templates — reference implementations for plugin authors.

These are *not* registered by default: forge's current
``docker-compose.yml.j2`` hardcodes the core services (postgres, redis,
keycloak, gatekeeper, traefik) because they're foundational to the
default stack. Plugin authors wanting to ship a similar sidecar can
copy one of these and call ``register_service(capability, template)``
from their plugin's ``register()`` entry point.

See ``docs/plugin-development.md`` for an end-to-end walkthrough.
"""

from __future__ import annotations

from forge.services.registry import ServiceTemplate

QDRANT_TEMPLATE = ServiceTemplate(
    name="qdrant",
    image="qdrant/qdrant:latest",
    ports=['"6333:6333"'],
    volumes=["qdrant_data:/qdrant/storage"],
    named_volumes=("qdrant_data",),
    healthcheck={
        "test": ["CMD-SHELL", "curl -f http://localhost:6333/readyz || exit 1"],
        "interval": "10s",
        "timeout": "5s",
        "retries": 5,
    },
)


CHROMA_TEMPLATE = ServiceTemplate(
    name="chroma",
    image="chromadb/chroma:latest",
    ports=['"8000:8000"'],
    volumes=["chroma_data:/chroma/chroma"],
    named_volumes=("chroma_data",),
    environment={"IS_PERSISTENT": "TRUE"},
)


WEAVIATE_TEMPLATE = ServiceTemplate(
    name="weaviate",
    image="semitechnologies/weaviate:latest",
    ports=['"8080:8080"'],
    volumes=["weaviate_data:/var/lib/weaviate"],
    named_volumes=("weaviate_data",),
    environment={
        "QUERY_DEFAULTS_LIMIT": "25",
        "PERSISTENCE_DATA_PATH": "/var/lib/weaviate",
        "DEFAULT_VECTORIZER_MODULE": "none",
    },
)


MINIO_TEMPLATE = ServiceTemplate(
    name="minio",
    image="minio/minio:latest",
    command=["server", "/data", "--console-address", ":9001"],
    ports=['"9000:9000"', '"9001:9001"'],
    volumes=["minio_data:/data"],
    named_volumes=("minio_data",),
    environment={
        "MINIO_ROOT_USER": "minio",
        "MINIO_ROOT_PASSWORD": "minio123",
    },
    healthcheck={
        "test": ["CMD-SHELL", "curl -f http://localhost:9000/minio/health/live || exit 1"],
        "interval": "30s",
        "timeout": "20s",
        "retries": 3,
    },
)


__all__ = [
    "CHROMA_TEMPLATE",
    "MINIO_TEMPLATE",
    "QDRANT_TEMPLATE",
    "WEAVIATE_TEMPLATE",
]
