"""SQL connector — read paginated rows / insert via SQLAlchemy core.

Reads execute the configured ``query`` (must be a ``SELECT``) with
keyset pagination via ``ORDER BY {cursor_column}`` + a
``WHERE {cursor_column} > :cursor`` clause appended at runtime.

Writes accept a ``table`` name + a list of column-mapped dicts. With
``upsert_columns`` set, conflicts dedupe on those columns (Postgres
``ON CONFLICT DO NOTHING`` only).

Each ``iter_records`` / ``write_records`` call opens a fresh
``AsyncEngine`` and disposes it — fine for short syncs, but wrap with a
pooled engine for chatty per-row workloads.

Vendored, self-contained: imports only the stdlib + pydantic +
sqlalchemy (a base-template dependency; install an async driver such as
asyncpg for Postgres — aiosqlite ships in the base).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorPage,
    WriteResult,
)


class SQLConfig(BaseModel):
    dsn: str | None = Field(
        None,
        description=(
            "SQLAlchemy async DSN — e.g. ``sqlite+aiosqlite:///:memory:`` "
            "or ``postgresql+asyncpg://user:pass@host/db``. Optional when "
            "supplied via ``secrets.dsn`` (the credential-bearing path), "
            "keeping the DSN out of any config JSON."
        ),
    )
    mode: Literal["read", "write"] = Field(
        "read",
        description="Read drives iter_records via query; write drives write_records.",
    )
    # Read-mode fields
    query: str | None = Field(
        None,
        description="SELECT statement. Must include {cursor_column} when paginated.",
    )
    cursor_column: str | None = Field(
        None,
        description=(
            "Column name used for keyset pagination — values must be "
            "monotonically increasing (id, created_at, etc.)."
        ),
    )
    chunk_size: int = Field(500, ge=1, le=10_000)
    # Write-mode fields
    table: str | None = Field(None, description="Target table name (write mode).")
    upsert_columns: list[str] | None = Field(
        None,
        description=(
            "Postgres-only — when set, INSERT … ON CONFLICT (cols) DO "
            "NOTHING is used so retries don't double-write."
        ),
    )
    auto_create_table: bool = Field(
        False,
        description=(
            "OPT-IN, default OFF. Write mode (Postgres only). When True, "
            "emit ``CREATE TABLE IF NOT EXISTS <table> (<cols TEXT>)`` "
            "before the INSERT loop, with column names taken from the "
            "union of keys across the first batch. Leave this off unless "
            "you explicitly want the connector to issue DDL — the "
            "connecting role must hold CREATE on the target schema, and "
            "all columns are created as TEXT. Prefer creating the "
            "destination table via your migrations instead."
        ),
    )


class SQLSecrets(BaseModel):
    """Optional secret bag — supplies the credential-bearing ``dsn``.

    When ``dsn`` is supplied here, :attr:`SQLConfig.dsn` may be ``None`` —
    the connector falls back to ``secrets.dsn`` at engine-create time so
    the DSN (and any embedded credentials) stays out of config JSON.
    """

    dsn: str | None = None


class SQLConnector(Connector):
    """Reads / writes via SQLAlchemy."""

    name = "sql"
    display_name = "SQL"
    capabilities = "both"
    ConfigModel = SQLConfig
    SecretsModel = SQLSecrets

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"SQLConnector(mode={self.cfg.mode!r})"

    @property
    def cfg(self) -> SQLConfig:
        return self._config  # type: ignore[return-value]

    @property
    def sec(self) -> SQLSecrets | None:
        return self._secrets  # type: ignore[return-value]

    def _resolved_dsn(self) -> str:
        s = self.sec
        if s and s.dsn:
            return s.dsn
        if self.cfg.dsn:
            return self.cfg.dsn
        raise ConnectorError(
            "SQLConnector requires a DSN in config.dsn or secrets.dsn",
        )

    async def iter_records(
        self,
        cursor: dict[str, Any] | None = None,
    ) -> AsyncIterator[ConnectorPage]:
        cfg = self.cfg
        if cfg.mode != "read":
            raise ConnectorError("SQLConnector configured with mode != 'read'")
        if not cfg.query:
            raise ConnectorError("SQLConnector read requires `query`")
        if not cfg.cursor_column:
            raise ConnectorError("SQLConnector read requires `cursor_column`")

        engine = create_async_engine(self._resolved_dsn())
        try:
            cursor_value: Any | None = (cursor or {}).get("after")
            while True:
                # Minimal SQL synthesis: append a keyset filter + ORDER BY
                # + LIMIT. The user-provided query owns any pre-existing
                # WHEREs / joins.
                base = cfg.query.rstrip().rstrip(";")
                if cursor_value is None:
                    sql = (
                        f"SELECT * FROM ({base}) AS sub "
                        f"ORDER BY {cfg.cursor_column} ASC LIMIT :_limit"
                    )
                    params = {"_limit": cfg.chunk_size}
                else:
                    sql = (
                        f"SELECT * FROM ({base}) AS sub "
                        f"WHERE {cfg.cursor_column} > :_after "
                        f"ORDER BY {cfg.cursor_column} ASC LIMIT :_limit"
                    )
                    params = {"_after": cursor_value, "_limit": cfg.chunk_size}
                async with engine.connect() as conn:
                    result = await conn.execute(text(sql), params)
                    rows = [dict(row._mapping) for row in result]

                done = len(rows) < cfg.chunk_size
                advance: dict[str, Any] | None = None
                if rows:
                    cursor_value = rows[-1].get(cfg.cursor_column)
                    advance = {"after": cursor_value}
                yield ConnectorPage(
                    records=rows,
                    cursor=advance,
                    done=done,
                )
                if done:
                    return
        finally:
            await engine.dispose()

    async def write_records(
        self,
        records: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> WriteResult:
        cfg = self.cfg
        if cfg.mode != "write":
            raise ConnectorError("SQLConnector configured with mode != 'write'")
        if not cfg.table:
            raise ConnectorError("SQLConnector write requires `table`")
        if not records:
            return WriteResult(written=0)

        # Use the column union across the batch so heterogeneous records
        # don't silently lose fields.
        columns: list[str] = sorted({k for r in records for k in r.keys()})
        col_list = ", ".join(f'"{c}"' for c in columns)
        param_list = ", ".join(f":{c}" for c in columns)
        sql = f'INSERT INTO "{cfg.table}" ({col_list}) VALUES ({param_list})'

        engine = create_async_engine(self._resolved_dsn())
        try:
            written = 0
            async with engine.begin() as conn:
                if cfg.auto_create_table and engine.dialect.name == "postgresql":
                    # OPT-IN DDL: all columns TEXT to avoid type-inference
                    # surprises across heterogeneous source shapes. The
                    # connecting role must hold CREATE on its schema.
                    # IF NOT EXISTS keeps retries safe.
                    ddl_cols = ", ".join(f'"{c}" TEXT' for c in columns)
                    await conn.execute(
                        text(f'CREATE TABLE IF NOT EXISTS "{cfg.table}" ({ddl_cols})')
                    )
                if cfg.upsert_columns and engine.dialect.name == "postgresql":
                    on_conflict = ", ".join(f'"{c}"' for c in cfg.upsert_columns)
                    sql_pg = f"{sql} ON CONFLICT ({on_conflict}) DO NOTHING"
                    for r in records:
                        # Fill missing columns with None so the bind list matches.
                        params = {c: r.get(c) for c in columns}
                        await conn.execute(text(sql_pg), params)
                        written += 1
                else:
                    for r in records:
                        params = {c: r.get(c) for c in columns}
                        await conn.execute(text(sql), params)
                        written += 1
            return WriteResult(written=written)
        finally:
            await engine.dispose()
