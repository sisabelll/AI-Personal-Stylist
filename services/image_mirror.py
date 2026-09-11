"""
Mirror remote inspiration images into Supabase Storage.

Instagram hands out signed CDN URLs whose `oe` query param is a hex expiry a
couple of weeks out. Storing that URL and rendering it later is why the board
goes blank: every fetch comes back 403 and the card is dropped. Mirroring the
bytes once at ingest gives the board a permanent, unsigned, non-rotating URL.

The storage path is content-addressed by `image_identity`, so re-scraping the
same photo from a different CDN edge overwrites the same object instead of
creating a second copy.
"""
from __future__ import annotations

import mimetypes
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.config import get_logger
from services.image_identity import image_dedupe_key

logger = get_logger(__name__)

BUCKET_NAME = "inspiration"

# Anything smaller is almost always a 1x1 tracker or an error placeholder.
_MIN_IMAGE_BYTES = 5000

_EXT_BY_CTYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

# Some fashion CDNs (net-a-porter among them) stall rather than reject when the
# request doesn't look like a browser, so send a full browser-ish header set.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_bucket_ready = False


def download_image(url: str, timeout: int = 15) -> Optional[Tuple[bytes, str]]:
    """
    Fetch an image. Returns (bytes, content_type) or None if it isn't usable.

    None covers every "don't store this" case: non-HTTP scheme, non-200,
    non-image content type, and bodies too small to be a real photo.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, timeout=timeout, headers=_BROWSER_HEADERS, allow_redirects=True)
    except Exception as e:
        logger.debug("[image_mirror] download failed %s: %s", url[:80], e)
        return None

    if resp.status_code != 200:
        logger.debug("[image_mirror] status %s for %s", resp.status_code, url[:80])
        return None

    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if "image" not in ctype:
        return None
    if not resp.content or len(resp.content) < _MIN_IMAGE_BYTES:
        return None
    return resp.content, ctype


def ensure_bucket(client) -> bool:
    """
    Create the public `inspiration` bucket if it doesn't exist yet. Idempotent.

    Returns False when storage is unreachable, which lets callers fall back to
    the original URL rather than dropping the item.
    """
    global _bucket_ready
    if _bucket_ready:
        return True
    try:
        client.storage.get_bucket(BUCKET_NAME)
        _bucket_ready = True
        return True
    except Exception:
        pass
    try:
        client.storage.create_bucket(
            BUCKET_NAME,
            options={
                "public": True,
                "allowed_mime_types": sorted(_EXT_BY_CTYPE.keys()),
                "file_size_limit": 10 * 1024 * 1024,
            },
        )
        logger.info("[image_mirror] created public bucket %r", BUCKET_NAME)
        _bucket_ready = True
        return True
    except Exception as e:
        # Most often "already exists" lost a race with another worker.
        try:
            client.storage.get_bucket(BUCKET_NAME)
            _bucket_ready = True
            return True
        except Exception:
            logger.warning("[image_mirror] bucket unavailable: %s", e)
            return False


def storage_path(user_id: str, image_url: str, ctype: str) -> str:
    """Content-addressed object path: same photo -> same path, every time."""
    ext = _EXT_BY_CTYPE.get(ctype) or mimetypes.guess_extension(ctype) or ".jpg"
    return f"{user_id}/{image_dedupe_key(image_url)}{ext}"


def mirror_image(client, user_id: str, image_url: str) -> Optional[str]:
    """
    Download `image_url` and upload it to Supabase Storage.

    Returns the permanent public URL, or None if the source image could not be
    fetched (expired signature, hotlink block, dead host).
    """
    if not ensure_bucket(client):
        return None

    downloaded = download_image(image_url)
    if downloaded is None:
        return None
    content, ctype = downloaded
    path = storage_path(user_id, image_url, ctype)

    try:
        client.storage.from_(BUCKET_NAME).upload(
            path,
            content,
            {"content-type": ctype, "upsert": "true", "cache-control": "public, max-age=31536000"},
        )
    except Exception as e:
        logger.warning("[image_mirror] upload failed for %s: %s", path, e)
        return None

    try:
        return client.storage.from_(BUCKET_NAME).get_public_url(path)
    except Exception as e:
        logger.warning("[image_mirror] public url failed for %s: %s", path, e)
        return None


def mirror_items(
    client,
    user_id: str,
    items: List[Dict[str, Any]],
    max_workers: int = 8,
) -> Dict[str, int]:
    """
    Mirror every item's image in parallel, rewriting `image_url` in place to the
    permanent URL. Items whose source image is already dead keep their original
    URL and are marked with `_mirror_failed` so the caller can drop them.

    Returns {"mirrored": n, "failed": n}.
    """
    if not items:
        return {"mirrored": 0, "failed": 0, "storage_available": True}

    # If the object store itself is unreachable, every upload will fail and the
    # caller would drop every item — turning a misconfigured deployment into a
    # silently empty board. Degrade to the pre-mirroring behaviour instead:
    # keep the original URLs, which at least render wherever they are not
    # hotlink-protected. The common cause is a runtime with no
    # SUPABASE_SERVICE_KEY, where the anon role cannot create or write the
    # bucket (get_bucket 404, upload 403 row-level security).
    if not ensure_bucket(client):
        logger.warning(
            "[image_mirror] object store unavailable — keeping original image URLs "
            "for %d item(s). Images will expire as before. Check SUPABASE_SERVICE_KEY.",
            len(items),
        )
        return {"mirrored": 0, "failed": 0, "storage_available": False}

    def _one(item: Dict[str, Any]) -> bool:
        original = item.get("image_url") or ""
        permanent = mirror_image(client, user_id, original)
        if permanent:
            item["image_url"] = permanent
            item["_source_url"] = original
            return True
        item["_mirror_failed"] = True
        return False

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_one, items))

    mirrored = sum(1 for ok in results if ok)
    return {
        "mirrored": mirrored,
        "failed": len(results) - mirrored,
        "storage_available": True,
    }
