"""Chat file upload / download endpoints.

Not auth-gated by default (matches /tools and /ws/agent). Wrap with your
project's auth dependency before production. Files land under ``UPLOAD_DIR``
(default ``./uploads``), namespaced by the ``customer_id`` form field —
supply it from your auth layer to keep tenants isolated.

Persistence of ``ChatFile`` DB rows is left to the caller: the upload
response includes everything needed (``id``, ``storage_path``, ``size_bytes``,
``mime_type``) to write a row into the shipped ``chat_files`` table yourself.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.services.chat_file_service import get_storage, save_uploaded_file

router = APIRouter()

# UUID used when no customer_id is supplied — dev-mode convenience, NOT
# safe for multi-tenant production use.
_ANON_CUSTOMER = uuid.UUID("00000000-0000-0000-0000-000000000000")


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    customer_id: str | None = Form(default=None),
) -> dict:
    try:
        cid = uuid.UUID(customer_id) if customer_id else _ANON_CUSTOMER
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid customer_id: {e}",
        ) from e
    stored = await save_uploaded_file(upload=file, customer_id=cid)
    file_id = uuid.uuid4()
    return {
        "id": str(file_id),
        "filename": file.filename,
        "mime_type": file.content_type,
        "size_bytes": stored.size_bytes,
        "storage_path": stored.storage_path,
    }


@router.get("/{storage_path:path}")
async def download_file(storage_path: str) -> FileResponse:
    # Reject path-traversal attempts up front. ``save_uploaded_file`` writes
    # relative paths only, so any ``..`` here is an attacker probing.
    if ".." in Path(storage_path).parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="path traversal not allowed",
        )
    full = get_storage().path_for(storage_path)
    if not full.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    return FileResponse(str(full))
