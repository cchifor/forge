"""Async client for the Airlock sandbox orchestrator.

Vendored, dependency-free (stdlib + httpx + pydantic) client for the
Airlock sandbox REST API. Exposes the async surface a service needs to
create sandboxes, exec commands, move files, and stream output — plus the
shared retry policy. There is no hard dependency on any private SDK.

    from app.airlock import AsyncAirlockClient, CreateSandboxParams

    async with AsyncAirlockClient(base_url="http://airlock:5100") as client:
        sandbox = await client.create(
            CreateSandboxParams(app_id="job-42", image="python:3.13-slim")
        )
        result = await sandbox.exec("echo hello")
        await sandbox.teardown()
"""

from __future__ import annotations

from app.airlock.client import AsyncAirlockClient
from app.airlock.context import (
    build_propagation_headers,
    get_correlation_id,
    set_correlation_id,
)
from app.airlock.errors import (
    AirlockError,
    AirlockNotFoundError,
    AirlockTimeoutError,
)
from app.airlock.retry import DEFAULT_RETRY_POLICY, RetryPolicy
from app.airlock.sandbox import AsyncAirlockSandboxHandle
from app.airlock.types import (
    CreateSandboxParams,
    ExecChunk,
    ExecResult,
    FileInfo,
    SandboxInfo,
)

__all__ = [
    "DEFAULT_RETRY_POLICY",
    "AirlockError",
    "AirlockNotFoundError",
    "AirlockTimeoutError",
    "AsyncAirlockClient",
    "AsyncAirlockSandboxHandle",
    "CreateSandboxParams",
    "ExecChunk",
    "ExecResult",
    "FileInfo",
    "RetryPolicy",
    "SandboxInfo",
    "build_propagation_headers",
    "get_correlation_id",
    "set_correlation_id",
]
