"""Upload / retrieval / storage for chat files.

Local-storage backend only in v1 — files land under ``UPLOAD_DIR``
(default ``./uploads``) in a customer-scoped subdirectory. S3 support is
a one-class swap when it arrives; the service API stays the same.

MIME validation is deliberately permissive (text, PDF, common image
types) so users can push the surface they need without hitting a deny
list. Tighten per-service by setting ``ALLOWED_MIME_TYPES``.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

_DEFAULT_ALLOWED = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/pdf",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
}

_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


@dataclass(frozen=True)
class StoredFile:
    storage_path: str  # relative to UPLOAD_DIR for local storage
    size_bytes: int


def _upload_root() -> Path:
    root = Path(os.environ.get("UPLOAD_DIR", "./uploads")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowed_mime_types() -> set[str]:
    raw = os.environ.get("ALLOWED_MIME_TYPES")
    if raw:
        return {m.strip() for m in raw.split(",") if m.strip()}
    return set(_DEFAULT_ALLOWED)


def _max_size_bytes() -> int:
    try:
        return int(os.environ.get("MAX_UPLOAD_SIZE", str(_MAX_SIZE_BYTES)))
    except ValueError:
        return _MAX_SIZE_BYTES


class ChatFileStorage:
    """Concrete local-filesystem store. Swap for an S3 implementation that
    exposes the same ``save`` / ``delete`` interface to migrate transparently."""

    def __init__(self) -> None:
        self.root = _upload_root()

    async def save(self, *, customer_id: uuid.UUID, upload: UploadFile) -> StoredFile:
        _validate(upload)
        target_dir = self.root / str(customer_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4()
        # Keep the original filename so downloads don't lose context, but
        # namespace with a UUID so two users can upload "invoice.pdf"
        # without collision.
        safe_name = Path(upload.filename or "file.bin").name
        stored = target_dir / f"{file_id}__{safe_name}"
        size = 0
        max_size = _max_size_bytes()
        oversize = False
        with stored.open("wb") as fh:
            while chunk := await upload.read(1 << 20):  # 1 MB chunks
                size += len(chunk)
                if size > max_size:
                    oversize = True
                    break
                fh.write(chunk)
        if oversize:
            # Must close the handle before unlinking on Windows.
            stored.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"file exceeds max size {max_size} bytes",
            )
        relative = str(stored.relative_to(self.root))
        return StoredFile(storage_path=relative, size_bytes=size)

    def path_for(self, storage_path: str) -> Path:
        return self.root / storage_path

    def delete(self, storage_path: str) -> None:
        target = self.path_for(storage_path)
        target.unlink(missing_ok=True)


def _validate(upload: UploadFile) -> None:
    mime = (upload.content_type or "").lower()
    allowed = _allowed_mime_types()
    if mime and mime not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"mime type {mime!r} not in allowlist",
        )


# Process-wide singleton; cheap to construct so this is mostly for clarity.
_storage: ChatFileStorage | None = None


def get_storage() -> ChatFileStorage:
    global _storage
    if _storage is None:
        _storage = ChatFileStorage()
    return _storage


async def save_uploaded_file(
    *, upload: UploadFile, customer_id: uuid.UUID
) -> StoredFile:
    return await get_storage().save(customer_id=customer_id, upload=upload)


def clear_storage_singleton() -> None:
    """Test hook — reset the module-level storage so tests pick up a new
    ``UPLOAD_DIR`` env var. Prod code never calls this."""
    global _storage
    _storage = None
