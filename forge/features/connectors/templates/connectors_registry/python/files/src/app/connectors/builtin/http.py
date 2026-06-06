"""HTTP connector — paginated GET for reads, POST/PUT for writes.

Reads any JSON-array endpoint. Pagination is configurable: cursor
(dotted-path into the response), offset (page-size + page-number), or
``link_header`` (RFC 5988-style ``rel="next"``).

Writes are one request per record. Idempotency keys, when supplied,
ride as ``Idempotency-Key`` headers — gateways that honor the
convention dedupe naturally.

Vendored, self-contained: imports only the stdlib + pydantic + httpx.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorPage,
    WriteResult,
)


class HTTPConfig(BaseModel):
    url: str = Field(..., description="Base URL — request path is appended.")
    method: Literal["GET", "POST", "PUT", "PATCH"] = "GET"
    pagination: Literal["none", "cursor", "offset", "link_header"] = "none"
    cursor_param: str | None = Field(
        None,
        description="Query param name receiving the next-page cursor (cursor strategy).",
    )
    cursor_response_path: str | None = Field(
        None,
        description=(
            "Dotted-path into the response JSON for the next cursor "
            "(e.g. ``meta.next_cursor``). Cursor strategy only."
        ),
    )
    page_size: int = Field(100, ge=1, le=10_000)
    timeout_seconds: float = Field(30.0, ge=1.0, le=300.0)
    headers_extra: dict[str, str] | None = None


class HTTPSecrets(BaseModel):
    bearer_token: str | None = None
    api_key_header: str | None = None
    api_key_value: str | None = None


def _resolve_path(payload: Any, dotted: str) -> Any:
    """Tiny dotted-path resolver. Returns ``None`` when not found."""
    cur = payload
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class HTTPConnector(Connector):
    """Reads / writes JSON over HTTP."""

    name = "http"
    display_name = "HTTP"
    capabilities = "both"
    ConfigModel = HTTPConfig
    SecretsModel = HTTPSecrets

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"HTTPConnector(url={self.cfg.url!r})"

    @property
    def cfg(self) -> HTTPConfig:
        return self._config  # type: ignore[return-value]

    @property
    def sec(self) -> HTTPSecrets | None:
        return self._secrets  # type: ignore[return-value]

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        h: dict[str, str] = {"accept": "application/json"}
        if self.cfg.headers_extra:
            h.update(self.cfg.headers_extra)
        s = self.sec
        if s and s.bearer_token:
            h["authorization"] = f"Bearer {s.bearer_token}"
        if s and s.api_key_header and s.api_key_value:
            h[s.api_key_header] = s.api_key_value
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    async def iter_records(
        self,
        cursor: dict[str, Any] | None = None,
    ) -> AsyncIterator[ConnectorPage]:
        cfg = self.cfg
        params: dict[str, Any] = {}
        next_cursor = (cursor or {}).get("next") if cursor else None
        offset = int((cursor or {}).get("offset", 0))
        next_url: str | None = None

        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            while True:
                if cfg.pagination == "cursor" and next_cursor and cfg.cursor_param:
                    params[cfg.cursor_param] = next_cursor
                if cfg.pagination == "offset":
                    params["offset"] = offset
                    params["limit"] = cfg.page_size
                target = next_url or cfg.url
                resp = await client.request(
                    cfg.method, target, headers=self._headers(), params=params
                )
                resp.raise_for_status()
                data = resp.json()

                records: list[dict[str, Any]]
                if isinstance(data, list):
                    records = list(data)
                elif isinstance(data, dict) and isinstance(data.get("items"), list):
                    records = list(data["items"])
                else:
                    records = []

                # Decide stop condition + advance cursor.
                done = True
                advance: dict[str, Any] | None = None
                if cfg.pagination == "cursor":
                    nc = (
                        _resolve_path(data, cfg.cursor_response_path)
                        if cfg.cursor_response_path
                        else None
                    )
                    if nc:
                        done = False
                        advance = {"next": nc}
                        next_cursor = nc
                elif cfg.pagination == "offset":
                    if len(records) >= cfg.page_size:
                        done = False
                        offset += len(records)
                        advance = {"offset": offset}
                elif cfg.pagination == "link_header":
                    link = resp.headers.get("link") or ""
                    next_url = _parse_link_next(link)
                    if next_url:
                        done = False
                        advance = {"next_url": next_url}

                yield ConnectorPage(
                    records=records,
                    cursor=advance,
                    done=done,
                )
                if done:
                    return

    async def write_records(
        self,
        records: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> WriteResult:
        if self.cfg.method == "GET":
            raise ConnectorError("HTTPConnector configured with method=GET cannot write_records")
        if not records:
            return WriteResult(written=0)

        cfg = self.cfg
        written = 0
        skipped = 0
        errors: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            for i, record in enumerate(records):
                key = f"{idempotency_key}:{i}" if idempotency_key else None
                try:
                    resp = await client.request(
                        cfg.method,
                        cfg.url,
                        json=record,
                        headers=self._headers(key),
                    )
                    if resp.status_code == 409 and key:
                        # Treat 409 Conflict as "already written" when an
                        # idempotency key was supplied.
                        skipped += 1
                        continue
                    resp.raise_for_status()
                    written += 1
                except httpx.HTTPError as exc:
                    errors.append({"index": i, "error": str(exc)})
        return WriteResult(written=written, skipped=skipped, errors=errors)


def _parse_link_next(link_header: str) -> str | None:
    """RFC-5988 minimalist parser — extract URL with rel=next."""
    if not link_header:
        return None
    for part in link_header.split(","):
        segments = part.strip().split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip()
        if not (url.startswith("<") and url.endswith(">")):
            continue
        for seg in segments[1:]:
            seg = seg.strip()
            if seg.lower().replace(" ", "") == 'rel="next"':
                return url[1:-1]
    return None
