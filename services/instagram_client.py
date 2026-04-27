from __future__ import annotations
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from core.config import Config, get_logger

_MIN_POST_AGE_DAYS = 365 * 2   # ignore posts older than 2 years

logger = get_logger(__name__)

# Apify actor for Instagram profile posts
# https://apify.com/apify/instagram-profile-scraper
_ACTOR_ID = "shu8hvrXbJbY3Eb9W"
_BASE = "https://api.apify.com/v2"
_POLL_INTERVAL = 3   # seconds between status checks
_POLL_TIMEOUT = 90   # give up after this many seconds


class ApifyInstagramClient:
    """
    Fetches recent posts from public Instagram profiles via Apify's
    Instagram Profile Scraper actor.

    Requires APIFY_API_KEY in .env.
    Pricing: ~$0.004 per post scraped (well within budget for 6-12 posts/profile).
    """

    def __init__(self):
        self.api_key = Config.APIFY_API_KEY
        if not self.api_key:
            raise RuntimeError("Missing APIFY_API_KEY in environment")

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json"}

    def _profile_url(self, handle: str) -> str:
        return f"https://www.instagram.com/{handle.lstrip('@').strip()}/"

    def _extract_image_url(self, post: dict) -> Optional[str]:
        """Pull the best image URL from a post dict."""
        images = post.get("images") or []
        if images:
            return images[0]
        return post.get("displayUrl") or post.get("imageUrl")

    def _is_recent(self, post: dict) -> bool:
        """Return True if post is within the last 2 years."""
        ts = post.get("timestamp") or post.get("takenAtTimestamp")
        if not ts:
            return True  # unknown date — allow through
        try:
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_MIN_POST_AGE_DAYS)
            return dt >= cutoff
        except Exception:
            return True

    def fetch_profile_posts(
        self,
        handle: str,
        max_posts: int = 9,
    ) -> List[Dict[str, Any]]:
        """
        Scrape recent posts from one public Instagram profile.

        Returns a list of dicts with: image_url, page_url, caption.
        Returns [] on any error so callers stay resilient.
        """
        handle = handle.lstrip("@").strip()
        if not handle:
            return []

        url = f"{_BASE}/acts/{_ACTOR_ID}/runs?token={self.api_key}"
        payload = {
            "directUrls": [self._profile_url(handle)],
            "resultsLimit": max_posts,
        }

        try:
            r = requests.post(url, json=payload, headers=self._headers(), timeout=15)
            r.raise_for_status()
            run_id = r.json()["data"]["id"]
        except Exception as e:
            logger.warning("[Apify] Failed to start run for @%s: %s", handle, e)
            return []

        # Poll until finished
        status_url = f"{_BASE}/actor-runs/{run_id}?token={self.api_key}"
        deadline = time.time() + _POLL_TIMEOUT
        while time.time() < deadline:
            try:
                status_resp = requests.get(status_url, timeout=10).json()
                status = status_resp["data"]["status"]
                if status == "SUCCEEDED":
                    break
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    logger.warning("[Apify] Run %s ended with status %s for @%s", run_id, status, handle)
                    return []
            except Exception as e:
                logger.warning("[Apify] Poll error for run %s: %s", run_id, e)
                return []
            time.sleep(_POLL_INTERVAL)
        else:
            logger.warning("[Apify] Timed out waiting for run %s (@%s)", run_id, handle)
            return []

        # Fetch dataset items
        dataset_id = status_resp["data"]["defaultDatasetId"]
        items_url = f"{_BASE}/datasets/{dataset_id}/items?token={self.api_key}&format=json&limit={max_posts}"
        try:
            items_resp = requests.get(items_url, timeout=15)
            items_resp.raise_for_status()
            posts = items_resp.json()
        except Exception as e:
            logger.warning("[Apify] Failed to fetch dataset for @%s: %s", handle, e)
            return []

        results = []
        for post in posts:
            if not self._is_recent(post):
                continue
            image_url = self._extract_image_url(post)
            if not image_url:
                continue
            results.append({
                "image_url": image_url,
                "page_url": post.get("url") or (f"https://www.instagram.com/p/{post['shortCode']}/" if post.get("shortCode") else ""),
                "caption": (post.get("caption") or "")[:120],
            })

        logger.debug("[Apify] @%s → %d posts", handle, len(results))
        return results

    def fetch_profiles_batch(
        self,
        handles: List[str],
        max_posts_each: int = 9,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch posts for multiple handles in a single Apify run (cheaper than one run per handle).
        Returns {handle: [posts]}.
        """
        handles = [h.lstrip("@").strip() for h in handles if h]
        if not handles:
            return {}

        url = f"{_BASE}/acts/{_ACTOR_ID}/runs?token={self.api_key}"
        payload = {
            "directUrls": [self._profile_url(h) for h in handles],
            "resultsLimit": max_posts_each,
        }

        try:
            r = requests.post(url, json=payload, headers=self._headers(), timeout=15)
            r.raise_for_status()
            run_id = r.json()["data"]["id"]
        except Exception as e:
            logger.warning("[Apify] Batch run failed for %s: %s", handles, e)
            return {}

        status_url = f"{_BASE}/actor-runs/{run_id}?token={self.api_key}"
        deadline = time.time() + _POLL_TIMEOUT + len(handles) * 10
        status_resp: Dict = {}
        while time.time() < deadline:
            try:
                status_resp = requests.get(status_url, timeout=10).json()
                status = status_resp["data"]["status"]
                if status == "SUCCEEDED":
                    break
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    logger.warning("[Apify] Batch run %s: %s", run_id, status)
                    return {}
            except Exception as e:
                logger.warning("[Apify] Batch poll error: %s", e)
                return {}
            time.sleep(_POLL_INTERVAL)
        else:
            logger.warning("[Apify] Batch run timed out: %s", handles)
            return {}

        dataset_id = status_resp["data"]["defaultDatasetId"]
        limit = max_posts_each * len(handles)
        items_url = f"{_BASE}/datasets/{dataset_id}/items?token={self.api_key}&format=json&limit={limit}"
        try:
            posts = requests.get(items_url, timeout=20).json()
        except Exception as e:
            logger.warning("[Apify] Batch dataset fetch failed: %s", e)
            return {}

        by_handle: Dict[str, List] = {h: [] for h in handles}
        for post in posts:
            owner = (post.get("ownerUsername") or "").lower()
            if owner not in by_handle:
                continue
            if not self._is_recent(post):
                continue
            image_url = self._extract_image_url(post)
            if not image_url:
                continue
            by_handle[owner].append({
                "image_url": image_url,
                "page_url": post.get("url") or (f"https://www.instagram.com/p/{post['shortCode']}/" if post.get("shortCode") else ""),
                "caption": (post.get("caption") or "")[:120],
            })

        return by_handle
