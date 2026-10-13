"""Object storage. Keys look like `audio/<uuid>.ogg` or `images/<uuid>.png`.

Audio is never publicly addressable: it is only served through the token-checked stream endpoint.
Images are served through /api/v1/media/{key}, which also keeps stored URLs stable if the
backend changes (local disk in dev → S3 in production).
"""

import logging
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings

log = logging.getLogger(__name__)

CHUNK = 64 * 1024


class Storage(ABC):
    @abstractmethod
    def save(self, key: str, fileobj: BinaryIO, content_type: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        raise NotImplementedError

    def presigned_url(self, key: str, ttl_seconds: int) -> str | None:
        """Return a direct URL (S3) or None when the backend serves bytes itself."""
        return None


def _safe_key(key: str) -> str:
    parts = [p for p in key.replace("\\", "/").split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise ValueError("invalid storage key")
    return "/".join(parts)


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        path = (self.root / _safe_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid storage key")
        return path

    def save(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        with tmp.open("wb") as out:
            shutil.copyfileobj(fileobj, out, CHUNK)
        tmp.replace(path)  # atomic: readers never see a half-written file

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def size(self, key: str) -> int:
        return self.path(key).stat().st_size

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        remaining = end - start + 1
        with self.path(key).open("rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk


class S3Storage(Storage):
    def __init__(self, bucket: str, *, endpoint_url: str | None, region: str,
                 access_key: str | None, secret_key: str | None) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region,
                                   aws_access_key_id=access_key, aws_secret_access_key=secret_key)

    def save(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        self.client.upload_fileobj(fileobj, self.bucket, _safe_key(key), ExtraArgs={"ContentType": content_type})

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
            return True
        except ClientError:
            return False

    def size(self, key: str) -> int:
        return int(self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))["ContentLength"])

    def presigned_url(self, key: str, ttl_seconds: int) -> str:
        # S3 honours Range headers itself, so seeking works after the redirect.
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": _safe_key(key)}, ExpiresIn=ttl_seconds
        )


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return S3Storage(settings.s3_bucket, endpoint_url=settings.s3_endpoint_url, region=settings.s3_region,
                         access_key=settings.s3_access_key_id, secret_key=settings.s3_secret_access_key)
    return LocalStorage(settings.media_root)


def media_url(key: str) -> str:
    return f"/api/v1/media/{key}"
