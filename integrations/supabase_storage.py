"""Private Supabase Storage boundary for durable content assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import requests

from config.settings import settings


class SupabaseStorageError(RuntimeError):
    """Raised when durable content storage is unavailable or rejects a request."""


_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


@dataclass(slots=True)
class SupabaseStorageGateway:
    """Upload and retrieve private objects without exposing service credentials."""

    url: str = settings.supabase_url
    service_role_key: str = settings.supabase_service_role_key
    bucket: str = settings.supabase_storage_bucket
    timeout_seconds: float = 20.0

    @property
    def configured(self) -> bool:
        return bool(self.url.strip() and self.service_role_key.strip() and self.bucket.strip())

    def upload_image(self, data: bytes, content_type: str) -> str:
        if not self.configured:
            raise SupabaseStorageError("Durable image storage is not configured.")
        extension = _EXTENSIONS.get(content_type)
        if extension is None:
            raise SupabaseStorageError("Only JPEG, PNG, and WebP images are supported.")
        if not data:
            raise SupabaseStorageError("The uploaded image is empty.")
        if len(data) > settings.content_image_max_bytes:
            raise SupabaseStorageError("The uploaded image exceeds the 10 MB limit.")
        object_path = f"studio/{uuid4().hex}.{extension}"
        response = requests.post(
            self._object_url(object_path),
            headers={
                "Authorization": f"Bearer {self.service_role_key}",
                "apikey": self.service_role_key,
                "Content-Type": content_type,
                "x-upsert": "false",
            },
            data=data,
            timeout=self.timeout_seconds,
        )
        if response.status_code not in {200, 201}:
            raise SupabaseStorageError("Durable image storage rejected the upload.")
        return f"supabase://{self.bucket}/{object_path}"

    def read_bytes(self, storage_uri: str) -> bytes:
        bucket, object_path = _parse_storage_uri(storage_uri)
        if bucket != self.bucket:
            raise SupabaseStorageError("The image belongs to an unexpected storage bucket.")
        response = requests.get(
            self._object_url(object_path),
            headers={
                "Authorization": f"Bearer {self.service_role_key}",
                "apikey": self.service_role_key,
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise SupabaseStorageError("The stored image could not be retrieved.")
        return response.content

    def _object_url(self, object_path: str) -> str:
        root = self.url.rstrip("/")
        return f"{root}/storage/v1/object/{quote(self.bucket, safe='')}/{quote(object_path, safe='/')}"


def read_asset_bytes(path_or_uri: str) -> bytes:
    """Read local or private-Supabase bytes through one controlled boundary."""
    if path_or_uri.startswith("supabase://"):
        return SupabaseStorageGateway().read_bytes(path_or_uri)
    return Path(path_or_uri).expanduser().resolve().read_bytes()


def _parse_storage_uri(storage_uri: str) -> tuple[str, str]:
    if not storage_uri.startswith("supabase://"):
        raise SupabaseStorageError("Unsupported storage reference.")
    bucket_and_path = storage_uri.removeprefix("supabase://")
    bucket, separator, object_path = bucket_and_path.partition("/")
    if not separator or not bucket or not object_path or ".." in Path(object_path).parts:
        raise SupabaseStorageError("Invalid private storage reference.")
    return bucket, object_path
