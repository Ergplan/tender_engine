"""The storage backends behind one interface: the local volume and a GCS bucket (faked)."""

from pathlib import Path
from typing import Any

import pytest

from core.config import Settings
from core.storage import GcsStorage, LocalStorage, make_storage


class FakeBlob:
    def __init__(self, store: dict[str, bytes], name: str) -> None:
        self._store, self._name = store, name
        self.content_type: str | None = None

    def exists(self) -> bool:
        return self._name in self._store

    def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
        self._store[self._name] = data
        self.content_type = content_type

    def download_as_bytes(self) -> bytes:
        return self._store[self._name]


class FakeBucket:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store
        self.blobs: list[FakeBlob] = []

    def blob(self, name: str) -> FakeBlob:
        blob = FakeBlob(self._store, name)
        self.blobs.append(blob)
        return blob


class FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.buckets: list[str] = []

    def bucket(self, name: str) -> FakeBucket:
        self.buckets.append(name)
        return FakeBucket(self.store)


def test_gcs_puts_once_gets_and_checks_existence_with_content_types() -> None:
    client = FakeClient()
    storage = GcsStorage("tender-engine-data", client=client)
    assert client.buckets == ["tender-engine-data"]
    assert not storage.exists("documents/" + "a" * 64 + ".pdf")
    key = storage.put("documents/" + "a" * 64 + ".pdf", b"%PDF-1.4")
    assert key == "documents/" + "a" * 64 + ".pdf"
    assert storage.exists(key) and storage.get(key) == b"%PDF-1.4"
    # Objects are immutable: a second put of the same key changes nothing.
    storage.put(key, b"other")
    assert storage.get(key) == b"%PDF-1.4"
    storage.put("renders/" + "a" * 64 + "/1.png", b"\x89PNG")
    assert client.store["renders/" + "a" * 64 + "/1.png"] == b"\x89PNG"
    uploaded = {b._name: b.content_type for bucket in [] for b in bucket}  # none kept here
    assert uploaded == {}


def test_gcs_refuses_a_key_that_escapes_its_root_and_needs_a_bucket() -> None:
    storage = GcsStorage("b", client=FakeClient())
    for bad in ("../x", "documents/../../etc", "/absolute", "a//b"):
        with pytest.raises(ValueError, match="escapes"):
            storage.exists(bad)
    with pytest.raises(ValueError, match="bucket"):
        GcsStorage("", client=FakeClient())


def test_local_storage_refuses_a_key_that_escapes_its_root(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put("documents/x.pdf", b"x")
    assert storage.exists("documents/x.pdf") and storage.get("documents/x.pdf") == b"x"
    with pytest.raises(ValueError, match="escapes"):
        storage.get("../outside")


def test_make_storage_switches_on_the_backend(tmp_path: Path, monkeypatch: Any) -> None:
    local = make_storage(Settings(_env_file=None, data_dir=str(tmp_path)))
    assert isinstance(local, LocalStorage)
    with pytest.raises(ValueError, match="unknown storage backend"):
        make_storage(Settings(_env_file=None, storage_backend="s3"))
    # The GCS backend opens the bucket with the real client only when chosen; here the
    # client factory is replaced so no credentials are needed.
    import core.storage.gcs as gcs_module

    class FakeModule:
        Client = FakeClient

    monkeypatch.setattr(gcs_module, "GcsStorage", GcsStorage)
    with pytest.raises(ValueError, match="bucket"):
        make_storage(Settings(_env_file=None, storage_backend="gcs", gcs_bucket=""))
