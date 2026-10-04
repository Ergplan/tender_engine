"""File storage behind one interface. Phase 1 uses the local /data volume."""

from core.storage.base import Storage, make_storage
from core.storage.local import LocalStorage

__all__ = ["LocalStorage", "Storage", "make_storage"]
