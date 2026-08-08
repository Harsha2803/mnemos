"""`ObjectStore` over S3-compatible storage (MinIO locally, S3 in production).

`boto3` has no async client, so every call goes through
`anyio.to_thread.run_sync` (CodingStandards §3) — inline, a slow MinIO request
would stall the event loop for every other concurrent request, the same
argument `PasswordHasher` makes for argon2id.
"""

from __future__ import annotations

import anyio
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from mnemos.core.errors import DependencyUnavailableError, NotFoundError, UpstreamError


class S3ObjectStore:
    """`ObjectStore` over `boto3`'s S3 client, pointed at MinIO by default."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            # Path-style addressing: MinIO does not do virtual-hosted-style
            # buckets by default, and a signature mismatch there is a cryptic
            # 403 rather than an obviously wrong URL.
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        try:
            await anyio.to_thread.run_sync(self._put_sync, key, data, content_type)
        except ClientError as exc:
            raise UpstreamError("object storage rejected the write", reason=str(exc)) from exc

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        try:
            return await anyio.to_thread.run_sync(self._get_sync, key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise NotFoundError(f"object {key!r} not found") from exc
            raise UpstreamError("object storage rejected the read", reason=str(exc)) from exc

    def _get_sync(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    async def delete(self, key: str) -> None:
        try:
            await anyio.to_thread.run_sync(self._delete_sync, key)
        except ClientError as exc:
            raise UpstreamError("object storage rejected the delete", reason=str(exc)) from exc

    def _delete_sync(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    async def health(self) -> None:
        """Confirm the configured bucket exists and is reachable."""
        try:
            await anyio.to_thread.run_sync(self._head_bucket_sync)
        except ClientError as exc:
            raise DependencyUnavailableError(
                "object storage is unreachable", reason=str(exc)
            ) from exc

    def _head_bucket_sync(self) -> None:
        self._client.head_bucket(Bucket=self._bucket)
