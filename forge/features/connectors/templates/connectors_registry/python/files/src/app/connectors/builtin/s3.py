"""S3 connector — read JSONL/CSV objects under a prefix, write per-chunk.

Reads list every object under ``prefix`` (paginated server-side) and
yield parsed records page-by-page. Writes upload one object per
``write_records`` call with a deterministic key derived from the
optional ``idempotency_key``.

Requires ``boto3`` — install it if you enable the ``s3`` backend.

Vendored, self-contained: imports only the stdlib + pydantic (boto3 is
imported lazily so the connector is skippable when it's absent).
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorPage,
    WriteResult,
)


class S3Config(BaseModel):
    bucket: str = Field(..., min_length=1)
    prefix: str = Field("", description="Object-key prefix (read mode).")
    format: Literal["jsonl", "csv"] = "jsonl"
    region: str | None = None
    endpoint_url: str | None = Field(
        None,
        description="Override S3 endpoint (e.g. ``http://localhost:9000`` for MinIO).",
    )
    write_key_template: str = Field(
        "${prefix}batch-${idempotency_key}.jsonl",
        description=(
            "Template for the object key on writes. Variables: "
            "``${prefix}``, ``${idempotency_key}``."
        ),
    )


class S3Secrets(BaseModel):
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None


def _client(cfg: S3Config, secrets: S3Secrets | None) -> Any:
    """Lazy import + construct a boto3 S3 client.

    boto3's clients are sync; blocking calls are offloaded to a thread.
    """
    try:
        import boto3
    except ImportError as exc:
        raise ConnectorError(
            "S3Connector requires boto3 — install it to enable the s3 backend"
        ) from exc
    kwargs: dict[str, Any] = {}
    if cfg.region:
        kwargs["region_name"] = cfg.region
    if cfg.endpoint_url:
        kwargs["endpoint_url"] = cfg.endpoint_url
    if secrets:
        if secrets.aws_access_key_id:
            kwargs["aws_access_key_id"] = secrets.aws_access_key_id
        if secrets.aws_secret_access_key:
            kwargs["aws_secret_access_key"] = secrets.aws_secret_access_key
        if secrets.aws_session_token:
            kwargs["aws_session_token"] = secrets.aws_session_token
    return boto3.client("s3", **kwargs)


def _parse_body(body: bytes, fmt: str) -> list[dict[str, Any]]:
    text = body.decode("utf-8", errors="replace")
    out: list[dict[str, Any]] = []
    if fmt == "jsonl":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    elif fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            out.append(dict(row))
    return out


class S3Connector(Connector):
    """Reads objects under a prefix; writes one object per call."""

    name = "s3"
    display_name = "S3"
    capabilities = "both"
    ConfigModel = S3Config
    SecretsModel = S3Secrets

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"S3Connector(bucket={self.cfg.bucket!r}, prefix={self.cfg.prefix!r})"

    @property
    def cfg(self) -> S3Config:
        return self._config  # type: ignore[return-value]

    @property
    def sec(self) -> S3Secrets | None:
        return self._secrets  # type: ignore[return-value]

    async def iter_records(
        self,
        cursor: dict[str, Any] | None = None,
    ) -> AsyncIterator[ConnectorPage]:
        import asyncio

        client = _client(self.cfg, self.sec)
        continuation_token = (cursor or {}).get("token")

        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self.cfg.bucket,
                "Prefix": self.cfg.prefix or "",
                "MaxKeys": 100,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token

            resp = await asyncio.to_thread(client.list_objects_v2, **kwargs)
            keys: list[str] = [obj["Key"] for obj in resp.get("Contents", []) if "Key" in obj]
            records: list[dict[str, Any]] = []
            for key in keys:
                body_resp = await asyncio.to_thread(
                    client.get_object,
                    Bucket=self.cfg.bucket,
                    Key=key,
                )
                body_bytes = body_resp["Body"].read()
                records.extend(_parse_body(body_bytes, self.cfg.format))

            next_token = resp.get("NextContinuationToken")
            done = not resp.get("IsTruncated")
            yield ConnectorPage(
                records=records,
                cursor={"token": next_token} if next_token else None,
                done=done,
            )
            if done:
                return
            continuation_token = next_token

    async def write_records(
        self,
        records: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> WriteResult:
        import asyncio

        if not records:
            return WriteResult(written=0)
        client = _client(self.cfg, self.sec)
        key = self.cfg.write_key_template.replace("${prefix}", self.cfg.prefix or "").replace(
            "${idempotency_key}",
            idempotency_key or uuid.uuid4().hex,
        )
        body = "".join(json.dumps(r, default=str) + "\n" for r in records).encode("utf-8")
        # Upload-then-skip on conflict — S3 has no native ON CONFLICT; we
        # HEAD the key first and skip when it already exists with the same
        # body length. Cheap belt-and-suspenders for retries.
        if idempotency_key:
            try:
                head = await asyncio.to_thread(
                    client.head_object,
                    Bucket=self.cfg.bucket,
                    Key=key,
                )
                if int(head.get("ContentLength", -1)) == len(body):
                    return WriteResult(written=0, skipped=len(records))
            except Exception:
                pass  # NoSuchKey or transient — fall through to upload
        await asyncio.to_thread(
            client.put_object,
            Bucket=self.cfg.bucket,
            Key=key,
            Body=body,
        )
        return WriteResult(written=len(records))
