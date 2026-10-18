from typing import Protocol

from core.config import Settings


class Storage(Protocol):
    """Keys are relative paths such as 'documents/<sha256>.pdf'. Objects are immutable."""

    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


def make_storage(settings: Settings) -> Storage:
    """`local` (the /data volume) or `gcs` (the bucket named by settings.gcs_bucket)."""
    from core.storage.local import LocalStorage

    if settings.storage_backend == "local":
        return LocalStorage(settings.data_dir)
    if settings.storage_backend == "gcs":
        from core.storage.gcs import GcsStorage

        return GcsStorage(settings.gcs_bucket)
    raise ValueError(f"unknown storage backend {settings.storage_backend!r}")
