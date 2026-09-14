"""GCS helpers — download media bytes for Chatwoot delivery."""

from __future__ import annotations

from google.cloud import storage

# Module-level singleton — one client, one connection pool, reused across all calls.
_client = storage.Client()


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    """Split 'gs://bucket/path/to/file' into (bucket, blob_path)."""
    without_scheme = gcs_uri.removeprefix("gs://")
    bucket, _, blob_path = without_scheme.partition("/")
    return bucket, blob_path


def _guess_content_type(blob_path: str) -> str:
    lower = blob_path.lower()
    if lower.endswith((".mp4", ".mov")):
        return "video/mp4"
    if lower.endswith((".jpeg", ".jpg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


def download_bytes(gcs_uri: str) -> tuple[bytes, str]:
    """Download a GCS object and return (raw_bytes, content_type).

    Content type is inferred from the filename — no metadata round trip needed
    because all product media files follow predictable naming (1.jpeg, 2.jpeg, 3.mp4).

    Raises google.cloud.exceptions.NotFound if the object does not exist.
    """
    bucket_name, blob_path = _parse_gcs_uri(gcs_uri)
    blob = _client.bucket(bucket_name).blob(blob_path)
    data = blob.download_as_bytes()
    return data, _guess_content_type(blob_path)
