"""Weaviate adapter for the VectorStorePort.

Uses a class-per-tenant isolation pattern. Weaviate's 4.x Python client
is sync-only for most operations; calls are wrapped in
``asyncio.to_thread`` to stay compatible with the async Protocol.
"""

from __future__ import annotations

import asyncio
from typing import Any

import weaviate
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.query import Filter

from app.ports.vector_store import VectorHit, VectorStorePort


class WeaviateAdapter(VectorStorePort):
    def __init__(self, url: str, api_key: str, class_prefix: str) -> None:
        auth = weaviate.auth.AuthApiKey(api_key) if api_key else None
        self._client = weaviate.connect_to_custom(
            http_host=_host(url),
            http_port=_port(url, default=8080),
            http_secure=url.startswith("https://"),
            grpc_host=_host(url),
            grpc_port=50051,
            grpc_secure=False,
            auth_credentials=auth,
            skip_init_checks=True,
        )
        self._prefix = class_prefix

    def _class_name(self, tenant_id: str) -> str:
        return f"{self._prefix}_{tenant_id}".replace("-", "_")

    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None:
        def _sync_upsert() -> None:
            collection = self._client.collections.get(self._class_name(tenant_id))
            with collection.batch.dynamic() as batch:
                for id_, vec, text, meta in vectors:
                    batch.add_object(
                        properties={"text": text, **meta},
                        vector=vec,
                        uuid=id_,
                    )
        await asyncio.to_thread(_sync_upsert)

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        def _sync_query() -> list[VectorHit]:
            collection = self._client.collections.get(self._class_name(tenant_id))
            where = _dict_to_filter(filters) if filters else None
            result = collection.query.near_vector(
                near_vector=embedding,
                limit=top_k,
                filters=where,
                return_metadata=["score"],
            )
            hits: list[VectorHit] = []
            for obj in result.objects:
                props = dict(obj.properties)
                text = str(props.pop("text", ""))
                hits.append(
                    VectorHit(
                        id=str(obj.uuid),
                        score=float(getattr(obj.metadata, "score", 0.0)) if obj.metadata else 0.0,
                        text=text,
                        metadata=props,
                    )
                )
            return hits
        return await asyncio.to_thread(_sync_query)

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None:
        def _sync_delete() -> None:
            collection = self._client.collections.get(self._class_name(tenant_id))
            collection.data.delete_many(where=Filter.by_id().contains_any(ids))
        await asyncio.to_thread(_sync_delete)

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None:
        def _sync_ensure() -> None:
            name = self._class_name(tenant_id)
            if self._client.collections.exists(name):
                return
            self._client.collections.create(
                name=name,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="text", data_type=DataType.TEXT),
                ],
            )
        await asyncio.to_thread(_sync_ensure)


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or "weaviate"


def _port(url: str, default: int) -> int:
    from urllib.parse import urlparse

    return urlparse(url).port or default


def _dict_to_filter(filters: dict[str, Any]):
    """Build a conjunction of equality filters from a flat dict."""
    current = None
    for key, value in filters.items():
        f = Filter.by_property(key).equal(value)
        current = f if current is None else current & f
    return current
