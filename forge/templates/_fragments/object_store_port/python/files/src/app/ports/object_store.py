"""Object-store port — capability contract for blob I/O.

Adapters live under ``app/adapters/object_store/<provider>.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class ObjectStorePort(Protocol):
    async def put(self, *, bucket: str, key: str, body: bytes, content_type: str | None = None) -> None:
        """Upload ``body`` to ``bucket/key``."""

    async def get(self, *, bucket: str, key: str) -> bytes:
        """Download ``bucket/key`` as bytes."""

    async def stream(self, *, bucket: str, key: str) -> AsyncIterator[bytes]:
        """Stream ``bucket/key`` in chunks — prefer this for large objects."""

    async def delete(self, *, bucket: str, key: str) -> None:
        """Remove the object."""

    async def presigned_url(
        self, *, bucket: str, key: str, ttl_seconds: int = 3600, method: str = "get"
    ) -> str:
        """Return a signed URL the client can use directly. ``method`` is
        ``get`` (download) or ``put`` (upload)."""
