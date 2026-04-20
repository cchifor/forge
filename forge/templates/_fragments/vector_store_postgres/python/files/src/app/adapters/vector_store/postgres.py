"""Postgres (pgvector) adapter for the VectorStorePort.

Uses a single table ``vectors`` partitioned by tenant_id — the default
multi-tenant shape for pgvector workloads that don't warrant a schema
per tenant. SQLAlchemy async engine is injected so connection pooling
and retry behaviour come from the rest of the app.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ports.vector_store import VectorHit, VectorStorePort


class PostgresAdapter(VectorStorePort):
    def __init__(self, engine: AsyncEngine, table: str = "vectors") -> None:
        self._engine = engine
        self._table = table

    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None:
        stmt = text(
            f"""
            INSERT INTO {self._table} (id, tenant_id, embedding, text, metadata)
            VALUES (:id, :tenant_id, :embedding, :text, CAST(:metadata AS jsonb))
            ON CONFLICT (id) DO UPDATE
              SET embedding = EXCLUDED.embedding,
                  text = EXCLUDED.text,
                  metadata = EXCLUDED.metadata;
            """
        )
        async with self._engine.begin() as conn:
            for id_, vec, text_body, meta in vectors:
                await conn.execute(
                    stmt,
                    {
                        "id": id_,
                        "tenant_id": tenant_id,
                        "embedding": str(vec),  # pgvector accepts "[1,2,3]" format
                        "text": text_body,
                        "metadata": json.dumps(meta),
                    },
                )

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        where_clauses = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": tenant_id, "embedding": str(embedding), "top_k": top_k}
        if filters:
            for i, (key, value) in enumerate(filters.items()):
                param = f"filter_{i}"
                where_clauses.append(f"metadata->>'{key}' = :{param}")
                params[param] = str(value)
        where = " AND ".join(where_clauses)
        stmt = text(
            f"""
            SELECT id, embedding <=> :embedding AS score, text, metadata
            FROM {self._table}
            WHERE {where}
            ORDER BY embedding <=> :embedding
            LIMIT :top_k;
            """
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt, params)
            rows = result.mappings().all()
        return [
            VectorHit(
                id=str(row["id"]),
                score=float(row["score"]),
                text=str(row["text"]),
                metadata=dict(row["metadata"] or {}),
            )
            for row in rows
        ]

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None:
        stmt = text(
            f"DELETE FROM {self._table} WHERE tenant_id = :tenant_id AND id = ANY(:ids)"
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt, {"tenant_id": tenant_id, "ids": ids})

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None:
        # Create the table + pgvector extension if needed. Idempotent.
        async with self._engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table} (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        embedding VECTOR({dim}),
                        text TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                    );
                    """
                )
            )
            await conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {self._table}_tenant_idx "
                    f"ON {self._table}(tenant_id);"
                )
            )
