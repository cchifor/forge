"""Local filesystem object-store adapter.

Writes blobs under ``<root>/<bucket>/<key>``. Useful for local dev,
testing, and air-gapped deployments. Not suitable for multi-instance
production — use S3 / GCS for that.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from collections.abc import AsyncIterator
from pathlib import Path

from app.ports.object_store import ObjectStorePort


class LocalObjectStoreAdapter(ObjectStorePort):
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        # Prevent path-traversal via ``..`` in keys.
        safe_key = key.replace("..", "_")
        return self._root / bucket / safe_key

    async def put(self, *, bucket: str, key: str, body: bytes, content_type: str | None = None) -> None:
        path = self._path(bucket, key)
        await asyncio.to_thread(_write_bytes, path, body)

    async def get(self, *, bucket: str, key: str) -> bytes:
        path = self._path(bucket, key)
        return await asyncio.to_thread(path.read_bytes)

    async def stream(self, *, bucket: str, key: str) -> AsyncIterator[bytes]:
        path = self._path(bucket, key)
        with path.open("rb") as f:
            while True:
                chunk = await asyncio.to_thread(f.read, 64 * 1024)
                if not chunk:
                    return
                yield chunk

    async def delete(self, *, bucket: str, key: str) -> None:
        path = self._path(bucket, key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def presigned_url(
        self, *, bucket: str, key: str, ttl_seconds: int = 3600, method: str = "get"
    ) -> str:
        # Local filesystem doesn't support real presigning; return a
        # file:// URL so tests can still assert on the shape. Production
        # setups should switch to the S3 adapter before exposing these.
        path = self._path(bucket, key)
        return f"file://{urllib.parse.quote(str(path))}"


def _write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
