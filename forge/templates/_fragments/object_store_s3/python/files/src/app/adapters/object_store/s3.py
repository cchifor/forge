"""AWS S3 / S3-compatible object-store adapter.

Works against real AWS S3 and S3-compatible endpoints (MinIO, Cloudflare
R2, Wasabi) via the ``endpoint_url`` override.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import aioboto3
from botocore.config import Config

from app.ports.object_store import ObjectStorePort


class S3ObjectStoreAdapter(ObjectStorePort):
    def __init__(
        self,
        region: str,
        access_key: str | None = None,
        secret_key: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._region = region
        self._endpoint = endpoint_url or None
        self._config = Config(signature_version="s3v4")
        self._session = aioboto3.Session(
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region,
        )

    def _client(self):
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            config=self._config,
        )

    async def put(self, *, bucket: str, key: str, body: bytes, content_type: str | None = None) -> None:
        kwargs = {"Bucket": bucket, "Key": key, "Body": body}
        if content_type:
            kwargs["ContentType"] = content_type
        async with self._client() as client:
            await client.put_object(**kwargs)

    async def get(self, *, bucket: str, key: str) -> bytes:
        async with self._client() as client:
            resp = await client.get_object(Bucket=bucket, Key=key)
            return await resp["Body"].read()

    async def stream(self, *, bucket: str, key: str) -> AsyncIterator[bytes]:
        async with self._client() as client:
            resp = await client.get_object(Bucket=bucket, Key=key)
            stream = resp["Body"]
            async for chunk in stream.iter_chunks(chunk_size=64 * 1024):
                yield chunk

    async def delete(self, *, bucket: str, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=bucket, Key=key)

    async def presigned_url(
        self, *, bucket: str, key: str, ttl_seconds: int = 3600, method: str = "get"
    ) -> str:
        operation = "get_object" if method == "get" else "put_object"
        async with self._client() as client:
            return await client.generate_presigned_url(
                operation,
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=ttl_seconds,
            )
