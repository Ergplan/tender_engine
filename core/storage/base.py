from typing import Protocol

from core.config import Settings


class Storage(Protocol):
    """Keys are relative paths such as 'documents/<sha256>.pdf'. Objects are immutable."""

    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


def make_storage(settings: Settings) -> Storage:
    from core.storage.local import LocalStorage

    if settings.storage_backend == "local":
        return LocalStorage(settings.data_dir)
    raise ValueError(f"unknown storage backend {settings.storage_backend!r}")
