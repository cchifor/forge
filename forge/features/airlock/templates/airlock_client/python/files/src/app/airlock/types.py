"""Airlock client data types."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecResult(BaseModel):
    """Result of executing a command in a sandbox."""

    stdout: str
    stderr: str
    exit_code: int
    exec_id: str | None = None


class ExecChunk(BaseModel):
    """One streamed chunk from ``AsyncAirlockSandboxHandle.exec_stream``.

    ``type`` is one of:
    - ``"meta"`` — carries the ``exec_id`` (always the first chunk).
    - ``"stdout"`` / ``"stderr"`` — bytes from the corresponding stream.
    - ``"exit"`` — final event; ``exit_code`` is set, ``data`` is empty.
    """

    type: str
    data: bytes = b""
    exec_id: str | None = None
    exit_code: int | None = None


class FileInfo(BaseModel):
    """A file or directory entry."""

    name: str
    path: str
    is_dir: bool
    size: int | None = None


class SandboxInfo(BaseModel):
    """Sandbox status and metadata."""

    id: str
    app_id: str
    tenant_id: str
    status: str
    container_id: str | None = None
    image_id: str | None = None
    host_rule: str | None = None
    port: int | None = None
    url: str | None = None
    ttl_seconds: int = 3600
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class CreateSandboxParams(BaseModel):
    """Parameters for creating a new sandbox."""

    app_id: str = Field(..., min_length=1, max_length=100)
    source_code_path: str | None = None
    image: str | None = None
    requirements: list[str] | None = None
    ttl_seconds: int = 3600
    container_port: int = 8000
    env_vars: dict[str, str] | None = None
    work_dir: str = "/app"
