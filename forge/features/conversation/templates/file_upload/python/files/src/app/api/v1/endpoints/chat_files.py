"""Chat file upload / download endpoints.

Auth-gated: the router below requires an authenticated user
(``Depends(get_current_user)``). Files land under ``UPLOAD_DIR`` (default
``./uploads``), namespaced by the caller's VERIFIED ``customer_id`` (the
tenant claim from the validated token) — never a request-supplied value.
Downloads are likewise scoped to the caller's own tenant prefix, so one
tenant cannot read another's uploads.

Persistence of ``ChatFile`` DB rows is left to the caller: the upload
response includes everything needed (``id``, ``storage_path``, ``size_bytes``,
``mime_type``) to write a row into the shipped ``chat_files`` table yourself.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from forge_core.domain.user import User
from forge_core.security.auth import get_current_user

from app.services.chat_file_service import get_storage, save_uploaded_file

# Chat-file upload/download must be authenticated AND tenant-scoped. The
# blanket router dependency is the gate; routes ALSO inject the user to
# derive the tenant namespace (FastAPI caches the dependency, so
# get_current_user runs once per request).
router = APIRouter(dependencies=[Depends(get_current_user)])


def _caller_customer_id(user: User) -> uuid.UUID:
    """The tenant namespace for storage, derived from the VERIFIED identity.

    ``User.customer_id`` is set from the token's ``tenant_id`` claim by the
    auth middleware — it is never attacker-controlled. Non-UUID tenant ids
    (e.g. the ``"public"`` anonymous fallback) are rejected: an
    auth-required router should never see them, but fail closed if it does.
    """
    try:
        return uuid.UUID(str(user.customer_id))
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no tenant context for chat-file storage",
        ) from e


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    user: User = Depends(get_current_user),
) -> dict:
    cid = _caller_customer_id(user)
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
async def download_file(
    storage_path: str,
    user: User = Depends(get_current_user),
) -> FileResponse:
    # Scope the download to the caller's own tenant prefix. ``path_for``
    # resolves + asserts containment under the upload root (defeating both
    # ``..`` and absolute-path escapes); here we additionally require the
    # resolved file to live under THIS tenant's subdirectory so one tenant
    # cannot read another's uploads even with a valid relative path.
    storage = get_storage()
    cid = _caller_customer_id(user)
    full = storage.path_for(storage_path)
    tenant_root = storage.path_for(str(cid))
    if full != tenant_root and tenant_root not in full.parents:
        # Same 404 as a missing file — don't leak whether other tenants'
        # files exist.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    if not full.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    return FileResponse(str(full))
