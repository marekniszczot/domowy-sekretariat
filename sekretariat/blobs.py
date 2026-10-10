"""Uploaded letter pages: the letters bucket in production, memory in tests."""

from typing import Protocol

from google.cloud import storage


class Blobs(Protocol):
    def put(self, path: str, data: bytes, mime_type: str) -> None: ...
    def get(self, path: str) -> tuple[bytes, str]: ...


class MemoryBlobs:
    def __init__(self):
        self.files: dict[str, tuple[bytes, str]] = {}

    def put(self, path, data, mime_type):
        self.files[path] = (data, mime_type)

    def get(self, path):
        return self.files[path]


class GcsBlobs:
    def __init__(self, client: storage.Client, bucket: str):
        self._bucket = client.bucket(bucket)

    def put(self, path, data, mime_type):
        self._bucket.blob(path).upload_from_string(data, content_type=mime_type)

    def get(self, path):
        blob = self._bucket.blob(path)
        data = blob.download_as_bytes()
        return data, blob.content_type
