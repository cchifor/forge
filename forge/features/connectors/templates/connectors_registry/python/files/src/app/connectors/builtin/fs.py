"""Filesystem connector — read/write JSONL or CSV files.

Reads stream a file as records (one per line for JSONL, one per row for
CSV). Writes append in the same format. Useful for smoke tests and
local-file scenarios.

Sandboxed: ``root_path`` constrains all I/O so a misconfigured caller
can't escape the configured directory.

Vendored, self-contained: imports only the stdlib + pydantic.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorPage,
    WriteResult,
)


class FilesystemConfig(BaseModel):
    root_path: str = Field(..., description="Sandbox root — all paths must resolve under here.")
    relative_path: str = Field(..., description="File path relative to root_path.")
    format: Literal["jsonl", "csv"] = "jsonl"
    chunk_size: int = Field(500, ge=1, le=10_000)
    csv_fieldnames: list[str] | None = Field(
        None, description="Required when format=csv and writing."
    )


class FilesystemConnector(Connector):
    """Reads / writes line-oriented files."""

    name = "fs"
    display_name = "Filesystem"
    capabilities = "both"
    ConfigModel = FilesystemConfig
    SecretsModel = None

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"FilesystemConnector(root={self.cfg.root_path!r}, path={self.cfg.relative_path!r})"

    @property
    def cfg(self) -> FilesystemConfig:
        return self._config  # type: ignore[return-value]

    def _resolved_path(self) -> Path:
        root = Path(self.cfg.root_path).resolve()
        target = (root / self.cfg.relative_path).resolve()
        # Defense against ``..`` traversal — confirm the resolved target
        # is rooted inside the sandbox.
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ConnectorError(f"path {self.cfg.relative_path!r} escapes root_path") from exc
        return target

    async def iter_records(
        self,
        cursor: dict[str, Any] | None = None,
    ) -> AsyncIterator[ConnectorPage]:
        path = self._resolved_path()
        if not path.is_file():
            yield ConnectorPage(records=[], cursor=None, done=True)
            return
        chunk: list[dict[str, Any]] = []
        offset = int((cursor or {}).get("offset", 0))
        # Re-open the file fresh; the records-per-chunk yield bounds memory.
        text = path.read_text(encoding="utf-8")
        line_no = 0
        if self.cfg.format == "jsonl":
            for line in text.splitlines():
                line_no += 1
                if line_no <= offset:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ConnectorError(f"jsonl parse error at line {line_no}: {exc}") from exc
                if len(chunk) >= self.cfg.chunk_size:
                    yield ConnectorPage(
                        records=chunk,
                        cursor={"offset": line_no},
                        done=False,
                    )
                    chunk = []
        elif self.cfg.format == "csv":
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                line_no += 1
                if line_no <= offset:
                    continue
                chunk.append(dict(row))
                if len(chunk) >= self.cfg.chunk_size:
                    yield ConnectorPage(
                        records=chunk,
                        cursor={"offset": line_no},
                        done=False,
                    )
                    chunk = []
        else:  # pragma: no cover — Pydantic validates upstream
            raise ConnectorError(f"unsupported format {self.cfg.format!r}")
        # Final partial chunk + done sentinel.
        yield ConnectorPage(records=chunk, cursor=None, done=True)

    async def write_records(
        self,
        records: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> WriteResult:
        if not records:
            return WriteResult(written=0)
        path = self._resolved_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.cfg.format == "jsonl":
            with path.open("a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, default=str))
                    f.write("\n")
            return WriteResult(written=len(records))
        if self.cfg.format == "csv":
            if not self.cfg.csv_fieldnames:
                raise ConnectorError("csv_fieldnames is required when writing csv")
            new_file = not path.exists() or path.stat().st_size == 0
            with path.open("a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.cfg.csv_fieldnames)
                if new_file:
                    writer.writeheader()
                for record in records:
                    writer.writerow({k: record.get(k, "") for k in self.cfg.csv_fieldnames})
            return WriteResult(written=len(records))
        raise ConnectorError(f"unsupported format {self.cfg.format!r}")
