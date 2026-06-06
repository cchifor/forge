"""Async per-sandbox operations handle."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import httpx

from app.airlock.context import build_propagation_headers
from app.airlock.errors import AirlockError, AirlockNotFoundError
from app.airlock.types import ExecChunk, ExecResult, FileInfo, SandboxInfo


class AsyncAirlockSandboxHandle:
    """Async handle for interacting with a specific Airlock sandbox."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        app_id: str,
        base_url: str,
        headers: dict[str, str],
    ) -> None:
        self._client = client
        self._app_id = app_id
        self._base_url = base_url
        self._headers = headers

    def _request_headers(self) -> dict[str, str]:
        """Static auth headers merged with trace-context propagation."""
        return build_propagation_headers(extra=self._headers)

    @property
    def app_id(self) -> str:
        return self._app_id

    def _url(self, path: str) -> str:
        return f"{self._base_url}/api/v1/sandboxes/{self._app_id}{path}"

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 404:
            raise AirlockNotFoundError(f"Sandbox '{self._app_id}' not found")
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                pass
            raise AirlockError(f"Airlock API error ({resp.status_code}): {detail}")

    async def exec(
        self, command: str, work_dir: str | None = None, timeout: int = 30
    ) -> ExecResult:
        resp = await self._client.post(
            self._url("/exec"),
            json={"command": command, "work_dir": work_dir, "timeout": timeout},
            headers=self._request_headers(),
            timeout=timeout + 10,
        )
        self._raise_for_status(resp)
        return ExecResult(**resp.json())

    async def read_file(self, path: str) -> bytes:
        resp = await self._client.get(
            self._url("/files"), params={"path": path}, headers=self._request_headers()
        )
        self._raise_for_status(resp)
        return resp.content

    async def write_file(self, path: str, content: str | bytes) -> None:
        if isinstance(content, bytes):
            payload = {
                "path": path,
                "content": base64.b64encode(content).decode(),
                "encoding": "base64",
            }
        else:
            payload = {"path": path, "content": content, "encoding": "utf-8"}
        resp = await self._client.put(
            self._url("/files"), json=payload, headers=self._request_headers()
        )
        self._raise_for_status(resp)

    async def list_dir(self, path: str = "/") -> list[FileInfo]:
        resp = await self._client.get(
            self._url("/ls"), params={"path": path}, headers=self._request_headers()
        )
        self._raise_for_status(resp)
        return [FileInfo(**item) for item in resp.json()]

    async def get_status(self) -> SandboxInfo:
        resp = await self._client.get(self._url(""), headers=self._request_headers())
        self._raise_for_status(resp)
        return SandboxInfo(**resp.json())

    async def teardown(self) -> None:
        resp = await self._client.post(self._url("/teardown"), headers=self._request_headers())
        self._raise_for_status(resp)

    async def extend_ttl(self, additional_seconds: int) -> None:
        resp = await self._client.post(
            self._url("/extend"),
            json={"additional_seconds": additional_seconds},
            headers=self._request_headers(),
        )
        self._raise_for_status(resp)

    async def exec_stream(
        self, command: str, work_dir: str | None = None, timeout: int = 30
    ) -> AsyncIterator[ExecChunk]:
        """Stream exec output as ``ExecChunk`` events in real time.

        The first chunk is always ``type="meta"`` carrying the
        ``exec_id`` — callers can pass it to ``cancel_exec`` to interrupt
        a long-running command. The final chunk is ``type="exit"`` with
        the integer exit code.
        """
        payload = {"command": command, "work_dir": work_dir, "timeout": timeout}
        headers = self._request_headers()
        async with self._client.stream(
            "POST",
            self._url("/exec/stream"),
            json=payload,
            headers=headers,
            timeout=timeout + 10,
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise AirlockError(
                    f"Airlock exec_stream error ({resp.status_code}): "
                    f"{body.decode(errors='replace')}"
                )
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                etype = event.get("type", "")
                if etype == "meta":
                    yield ExecChunk(type="meta", exec_id=event.get("exec_id"))
                elif etype == "exit":
                    yield ExecChunk(type="exit", exit_code=event.get("exit_code"))
                elif etype in ("stdout", "stderr"):
                    data = base64.b64decode(event.get("data", ""))
                    yield ExecChunk(type=etype, data=data)

    async def cancel_exec(self, exec_id: str) -> None:
        """Cancel an in-flight exec by its ``exec_id``.

        404 responses (exec already completed or unknown) are swallowed so
        callers can fire-and-forget without worrying about races.
        """
        resp = await self._client.post(
            self._url(f"/exec/{exec_id}/cancel"),
            headers=self._request_headers(),
        )
        if resp.status_code in (204, 404):
            return
        self._raise_for_status(resp)
