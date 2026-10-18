"""File storage behind one interface: the local /data volume, or a GCS bucket on Cloud Run."""

from core.storage.base import Storage, make_storage
from core.storage.gcs import GcsStorage
from core.storage.local import LocalStorage

__all__ = ["GcsStorage", "LocalStorage", "Storage", "make_storage"]
