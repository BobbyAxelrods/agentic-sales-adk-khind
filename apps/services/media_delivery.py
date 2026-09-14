"""Build GCS media-delivery plans from live bucket listings.

Filenames are discovered directly from GCS so local data_source files are
never consulted. Any rename or addition in the bucket is reflected immediately
without touching code.
"""

from __future__ import annotations

from google.cloud import storage

from apps.config import settings
from apps.prompts.khind_prompts import PRODUCT_MEDIA_FOLDERS

IMAGE_SUFFIXES = frozenset({".jpeg", ".jpg", ".png", ".webp"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm"})

# Reuse the same client as gcs.py — import the singleton.
# Imported inside the function to avoid circular imports at module load time.


def _list_product_media(folder: str) -> tuple[list[str], list[str]]:
    """Return (images[:2], videos[:1]) filenames from the GCS product folder.

    Files are sorted alphabetically so ordering is deterministic.
    """
    from apps.clients.gcs import _client  # module-level singleton

    prefix = f"{folder}/"
    blobs = sorted(
        _client.list_blobs(settings.gcs_bucket, prefix=prefix),
        key=lambda b: b.name,
    )

    images: list[str] = []
    videos: list[str] = []
    for blob in blobs:
        name = blob.name.removeprefix(prefix)
        # Skip "sub-folder" pseudo-entries (names ending with /)
        if not name or name.endswith("/"):
            continue
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix in IMAGE_SUFFIXES and len(images) < 2:
            images.append(name)
        elif suffix in VIDEO_SUFFIXES and len(videos) < 1:
            videos.append(name)

    return images, videos


def get_initial_media_plan(product_key: str, state: dict) -> dict:
    """Return the GCS URIs for initial product media (up to 2 images + 1 video).

    Filenames are read live from GCS — always reflects the actual bucket contents.
    State tracks which products have already been sent so delivery is at most once
    per session.

    The returned URIs are for the webhook delivery layer only and must never
    appear in an LLM prompt.
    """
    normalized_key = (product_key or "").strip().lower()
    if normalized_key not in PRODUCT_MEDIA_FOLDERS:
        return {"status": "error", "media": []}

    sent_products = set(state.get("initial_media_sent_products", []))
    if normalized_key in sent_products:
        return {"status": "already_sent", "media": []}

    folder = PRODUCT_MEDIA_FOLDERS[normalized_key]
    try:
        images, videos = _list_product_media(folder)
    except Exception:
        return {"status": "error", "media": []}

    if not images and not videos:
        return {"status": "error", "media": []}

    bucket = settings.gcs_bucket
    media = [
        {"media_type": "image", "gcs_uri": f"gs://{bucket}/{folder}/{f}"} for f in images
    ] + [
        {"media_type": "video", "gcs_uri": f"gs://{bucket}/{folder}/{f}"} for f in videos
    ]

    sent_products.add(normalized_key)
    state["initial_media_sent_products"] = sorted(sent_products)

    status = "ok" if len(images) == 2 and len(videos) == 1 else "incomplete"
    return {"status": status, "media": media}
