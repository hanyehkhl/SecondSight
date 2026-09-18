import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt


class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Invalid storage key: {key}")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


class S3Storage:
    """S3 / MinIO backend. boto3 is synchronous, so calls run in a worker thread."""

    def __init__(self) -> None:
        import boto3

        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value() if settings.s3_access_key else None,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None,
        )

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data)

    async def get(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)


class EncryptedStorage:
    """Wraps any backend so that bytes are Fernet-encrypted before they leave the process."""

    def __init__(self, inner: StorageBackend) -> None:
        self.inner = inner

    async def put(self, key: str, data: bytes) -> None:
        await self.inner.put(key, await asyncio.to_thread(encrypt, data))

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(decrypt, await self.inner.get(key))

    async def delete(self, key: str) -> None:
        await self.inner.delete(key)


@lru_cache
def get_storage() -> StorageBackend:
    settings = get_settings()
    inner: StorageBackend = (
        S3Storage() if settings.storage_backend == "s3" else LocalStorage(settings.storage_local_path)
    )
    return EncryptedStorage(inner)
