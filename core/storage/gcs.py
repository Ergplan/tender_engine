"""Google Cloud Storage behind the same interface as the local volume (Stage 5C).

Keys are object names in one bucket; objects are immutable, so a put of an existing key is
a no-op. The client library is imported only when a bucket is opened: a local run with
`STORAGE_BACKEND=local` never needs credentials."""

from typing import Any


class GcsStorage:
    def __init__(self, bucket: str, client: Any | None = None) -> None:
        if not bucket:
            raise ValueError("a GCS bucket name is required (GCS_BUCKET)")
        if client is None:
            from google.cloud import storage  # type: ignore[import-untyped]  # the SDK, on use

            client = storage.Client()
        self._bucket = client.bucket(bucket)

    def put(self, key: str, data: bytes) -> str:
        blob = self._bucket.blob(_key(key))
        if not blob.exists():
            blob.upload_from_string(data, content_type=_content_type(key))
        return key

    def get(self, key: str) -> bytes:
        data: bytes = self._bucket.blob(_key(key)).download_as_bytes()
        return data

    def exists(self, key: str) -> bool:
        found: bool = self._bucket.blob(_key(key)).exists()
        return found


def _key(key: str) -> str:
    """Keys are relative paths; a key that climbs out of its folder is refused, as the local
    backend refuses one that escapes its root."""
    parts = key.split("/")
    if key.startswith("/") or ".." in parts or "" in parts:
        raise ValueError(f"storage key escapes the root: {key!r}")
    return key


def _content_type(key: str) -> str:
    if key.endswith(".pdf"):
        return "application/pdf"
    if key.endswith(".png"):
        return "image/png"
    return "application/octet-stream"
