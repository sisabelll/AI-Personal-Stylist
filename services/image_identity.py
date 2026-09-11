"""
Stable identity for a remote image URL.

Both the inspiration board's duplicate problem and its blank-board problem come
from treating a CDN URL as if it identified a photo. It doesn't:

  * Instagram serves the same photo from a rotating edge host
    (scontent-lga3-1.cdninstagram.com, scontent-ord5-2.cdninstagram.com,
    instagram.fluk1-1.fna.fbcdn.net, ...), so hashing scheme+host+path gives a
    different key every scrape and the upsert inserts a new row instead of
    updating the existing one.
  * The signature lives in the query string (`oe` is a hex expiry), so the URL
    stops resolving after a couple of weeks.

`image_identity` collapses a URL to something that survives both: for Instagram
CDN URLs, the media filename stem (identical across every edge host and every
size variant); for everything else, scheme + host + path with the query dropped.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

# Instagram/Facebook CDN hosts. Both spellings appear in the same scrape.
_IG_HOSTS = ("cdninstagram.com", "fbcdn.net")

# Instagram media filenames look like:
#   657228158_18582636988003935_9084175833587828264_n.jpg
# <upload id>_<media id>_<owner id>_<size letter>.<ext>
# The three numeric groups are stable across edge hosts and size variants; the
# trailing size letter and extension are not, so both are dropped.
_IG_MEDIA_RE = re.compile(
    r"/(\d{6,}_\d{6,}_\d{6,})(?:_[a-z0-9]{1,3})?\.(?:jpg|jpeg|png|webp|heic)",
    re.IGNORECASE,
)


def is_instagram_cdn(url: str) -> bool:
    """True for Instagram/Facebook CDN URLs, which are host-rotating and signed."""
    u = (url or "").lower()
    return any(h in u for h in _IG_HOSTS)


def image_identity(url: str) -> str:
    """
    Reduce a URL to a stable per-photo identity.

    Returns "" for empty input so callers can skip the row.
    """
    u = (url or "").strip()
    if not u:
        return ""

    parts = urlsplit(u)

    if is_instagram_cdn(u):
        match = _IG_MEDIA_RE.search(parts.path)
        if match:
            # Host-free on purpose: the edge host is what rotates.
            return f"instagram:{match.group(1)}"
        # Unrecognised Instagram path — fall back to the path alone, still
        # dropping the host so edge rotation can't fork the identity.
        return f"instagram:{parts.path.lower()}"

    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, "", ""))


def image_dedupe_key(url: str) -> str:
    """SHA-1 of the stable identity. Empty string for an empty URL."""
    identity = image_identity(url)
    if not identity:
        return ""
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()
