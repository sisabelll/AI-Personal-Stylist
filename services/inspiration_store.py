from __future__ import annotations
from typing import List, Dict, Any
import hashlib
import re
from core.config import Config, get_logger
from urllib.parse import urlparse, urlunparse

logger = get_logger(__name__)

class InspirationStore:
    def __init__(self, storage_service):
        self.supabase = storage_service.supabase

    def _dedupe_key(self, image_url: str) -> str:
        u = (image_url or "").strip().lower()
        parsed = urlparse(u)
        # strip query params — same image often served with different params
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        return hashlib.sha1(clean.encode("utf-8")).hexdigest()

    def _is_valid_url(self, url: str) -> bool:
        if not url:
            return False
        return bool(re.match(r'https?://.+\..+', url))
    
    def upsert_items(self, user_id: str, items: List[Dict[str, Any]]) -> None:
        if not items:
            return

        payload = []
        for it in items:
            image_url = it["image_url"]
            payload.append({
                "user_id": user_id,
                "source_type": it["source_type"],
                "source_name": it["source_name"],
                "image_url": image_url,
                "page_url": it.get("page_url"),
                "caption": it.get("caption"),
                "tags": it.get("tags") or [],
                "score": float(it.get("score") or 0.0),
                "dedupe_key": self._dedupe_key(image_url),
            })

        items = [it for it in items if self._is_valid_url(it.get("image_url", ""))]

        deduped = {}
        for row in payload:
            k = (row["user_id"], row["dedupe_key"])
            prev = deduped.get(k)
            if prev is None:
                deduped[k] = row
            else:
                prev_tags = len(prev.get("tags") or [])
                row_tags = len(row.get("tags") or [])
                if row_tags > prev_tags or float(row.get("score") or 0) > float(prev.get("score") or 0):
                    deduped[k] = row

        payload = list(deduped.values())

        self.supabase.table("inspiration_items").upsert(
            payload,
            on_conflict="user_id,dedupe_key"
        ).execute()
    
    def fetch_top_items(self, user_id: str, limit: int = 60) -> List[dict]:
        resp = (
            self.supabase.table("inspiration_items")
            .select("*")
            .eq("user_id", user_id)
            .order("score", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def log_feedback(self, user_id: str, item_id: str, action: str) -> None:
        """Persist save/hide feedback. Requires a `feedback TEXT` column on inspiration_items.
        Add it in Supabase: ALTER TABLE inspiration_items ADD COLUMN feedback TEXT;
        """
        try:
            self.supabase.table("inspiration_items").update(
                {"feedback": action}
            ).eq("id", item_id).eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning(f"[InspirationStore] log_feedback failed: {e}")
            pass  # column not yet added — hide/save still work client-side
