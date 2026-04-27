from __future__ import annotations
from typing import List, Dict, Any
from datetime import datetime, timezone
import hashlib
import re
from core.config import get_logger
from urllib.parse import urlparse, urlunparse

logger = get_logger(__name__)

# Score deltas applied when the user interacts with the inspiration board
_FEEDBACK_DELTAS = {
    "like": 0.3,
    "save": 0.3,
    "hide": -1.0,    # effectively buries the item permanently
    "dislike": -0.3,
}


class InspirationStore:
    def __init__(self, storage_service):
        self.supabase = storage_service.supabase

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dedupe_key(self, image_url: str) -> str:
        u = (image_url or "").strip().lower()
        parsed = urlparse(u)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        return hashlib.sha1(clean.encode("utf-8")).hexdigest()

    def _is_valid_url(self, url: str) -> bool:
        if not url:
            return False
        return bool(re.match(r'https?://.+\..+', url))

    # ------------------------------------------------------------------
    # Inspiration items (the board)
    # ------------------------------------------------------------------

    def upsert_items(self, user_id: str, items: List[Dict[str, Any]]) -> None:
        if not items:
            return

        payload = []
        for it in items:
            image_url = it["image_url"]
            if not self._is_valid_url(image_url):
                continue
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

        # In-memory dedup: keep the row with the most tags (or highest score) per key
        deduped: Dict[tuple, dict] = {}
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

        try:
            self.supabase.table("inspiration_items").upsert(
                list(deduped.values()),
                on_conflict="user_id,dedupe_key"
            ).execute()
        except Exception as e:
            logger.warning("[InspirationStore] upsert_items failed (FK violation in dev?): %s", e)

    def delete_instagram_items(self, user_id: str) -> None:
        """Remove all Instagram items for a user so stale posts don't linger."""
        try:
            self.supabase.table("inspiration_items").delete().eq(
                "user_id", user_id
            ).eq("source_type", "instagram").execute()
        except Exception as e:
            logger.warning("[InspirationStore] delete_instagram_items failed: %s", e)

    def fetch_top_items(self, user_id: str, limit: int = 400) -> List[dict]:
        resp = (
            self.supabase.table("inspiration_items")
            .select("*")
            .eq("user_id", user_id)
            .neq("feedback", "hide")   # never surface hidden items
            .order("score", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def delete_item(self, user_id: str, item_id: str) -> None:
        """Permanently remove an item the user has hidden."""
        try:
            self.supabase.table("inspiration_items").delete().eq(
                "id", item_id
            ).eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning("[InspirationStore] delete_item failed: %s", e)

    def save_item(self, user_id: str, item_id: str) -> None:
        """Mark an item as saved and boost its score."""
        try:
            row_resp = (
                self.supabase.table("inspiration_items")
                .select("score")
                .eq("id", item_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            current_score = float((row_resp.data or {}).get("score") or 0.5)
            new_score = min(1.0, current_score + 0.3)
            self.supabase.table("inspiration_items").update({
                "feedback": "save",
                "score": new_score,
            }).eq("id", item_id).eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning("[InspirationStore] save_item failed: %s", e)

    def log_feedback(self, user_id: str, item_id: str, action: str) -> None:
        """
        Persist user feedback (like / save / hide / dislike) on an inspiration item.

        Applies a score delta so liked items float up and hidden items are buried.
        Falls back gracefully if the feedback or score columns aren't yet present.

        Required Supabase columns on inspiration_items:
          feedback TEXT
          score    FLOAT  (default 0.5)
        """
        delta = _FEEDBACK_DELTAS.get(action.lower())
        try:
            update_payload: Dict[str, Any] = {"feedback": action}
            if delta is not None:
                # Read current score, apply delta, clamp to [-1.0, 1.0]
                row_resp = (
                    self.supabase.table("inspiration_items")
                    .select("score")
                    .eq("id", item_id)
                    .eq("user_id", user_id)
                    .maybe_single()
                    .execute()
                )
                current_score = float((row_resp.data or {}).get("score") or 0.5)
                new_score = max(-1.0, min(1.0, current_score + delta))
                update_payload["score"] = new_score

            self.supabase.table("inspiration_items").update(
                update_payload
            ).eq("id", item_id).eq("user_id", user_id).execute()

        except Exception as e:
            logger.warning("[InspirationStore] log_feedback failed: %s", e)

    def fetch_feedback_signals(self, user_id: str) -> Dict[str, Any]:
        """
        Read like/hide counts per source_name from inspiration_items.
        Returns:
          promoted: sources liked ≥2 times (user resonates with this lane)
          demoted:  sources hidden ≥2 times (user wants less of this)
        """
        from collections import Counter
        try:
            liked = (
                self.supabase.table("inspiration_items")
                .select("source_name")
                .eq("user_id", user_id)
                .eq("feedback", "like")
                .execute()
            ).data or []
            hidden = (
                self.supabase.table("inspiration_items")
                .select("source_name")
                .eq("user_id", user_id)
                .eq("feedback", "hide")
                .execute()
            ).data or []
        except Exception as e:
            logger.warning("[InspirationStore] fetch_feedback_signals failed: %s", e)
            return {"promoted": [], "demoted": []}

        liked_counts  = Counter(r["source_name"] for r in liked)
        hidden_counts = Counter(r["source_name"] for r in hidden)
        return {
            "promoted": [n for n, c in liked_counts.items()  if c >= 2],
            "demoted":  [n for n, c in hidden_counts.items() if c >= 2],
        }

    # ------------------------------------------------------------------
    # Knowledge graph (expanded icons / motifs / brands per user)
    # ------------------------------------------------------------------
    #
    # Required Supabase table (run this migration once):
    #
    #   CREATE TABLE inspiration_knowledge (
    #     user_id               UUID PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    #     seed_icons            TEXT[]      DEFAULT '{}',
    #     seed_brands           TEXT[]      DEFAULT '{}',
    #     similar_icons         JSONB       DEFAULT '[]',
    #     motifs                JSONB       DEFAULT '[]',
    #     brand_angles          JSONB       DEFAULT '[]',
    #     promoted_icons        TEXT[]      DEFAULT '{}',
    #     promoted_brands       TEXT[]      DEFAULT '{}',
    #     demoted_sources       TEXT[]      DEFAULT '{}',
    #     updated_at            TIMESTAMPTZ DEFAULT now(),
    #     last_refreshed_at     TIMESTAMPTZ,
    #     refresh_interval_days INT         DEFAULT 7
    #   );

    def upsert_knowledge_graph(self, user_id: str, expanded: Dict[str, Any]) -> None:
        """Persist the LLM-expanded knowledge graph for a user (one row per user)."""

        def _serializable(v: Any) -> Any:
            """Ensure nested Pydantic objects are plain dicts/lists."""
            if hasattr(v, "model_dump"):
                return v.model_dump()
            if isinstance(v, list):
                return [_serializable(x) for x in v]
            return v

        # Merge new expansion into existing KG rather than replacing.
        # similar_icons and motifs accumulate up to a cap — this grows the
        # image query pool over time without re-fetching the same sources.
        _MAX_ICONS  = 40
        _MAX_MOTIFS = 25

        existing = self.fetch_knowledge_graph(user_id)

        def _merge_icons(existing_list, new_list, cap):
            seen = {(i.get("name") or "").lower() for i in existing_list}
            merged = list(existing_list)
            for item in new_list:
                name = (item.get("name") or "").lower()
                if name and name not in seen:
                    merged.append(item)
                    seen.add(name)
            return merged[:cap]

        def _merge_motifs(existing_list, new_list, cap):
            seen = {(m.get("phrase") or "").lower() for m in existing_list}
            merged = list(existing_list)
            for item in new_list:
                phrase = (item.get("phrase") or "").lower()
                if phrase and phrase not in seen:
                    merged.append(item)
                    seen.add(phrase)
            return merged[:cap]

        merged_icons  = _merge_icons(
            existing.get("similar_icons") or [],
            _serializable(expanded.get("similar_icons") or []),
            _MAX_ICONS,
        )
        merged_motifs = _merge_motifs(
            existing.get("motifs") or [],
            _serializable(expanded.get("motifs") or []),
            _MAX_MOTIFS,
        )
        # brand_angles: always replace (brands change, angles should stay fresh)
        merged_brands = _serializable(expanded.get("brand_angles") or [])

        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "user_id": user_id,
            "seed_icons": expanded.get("seed_icons") or [],
            "seed_brands": expanded.get("seed_brands") or [],
            "similar_icons": merged_icons,
            "motifs": merged_motifs,
            "brand_angles": merged_brands,
            "promoted_icons":  expanded.get("promoted_icons") or [],
            "promoted_brands": expanded.get("promoted_brands") or [],
            "demoted_sources": expanded.get("demoted_sources") or [],
            "updated_at": now_iso,
            "last_refreshed_at": now_iso,
        }

        try:
            self.supabase.table("inspiration_knowledge").upsert(
                payload, on_conflict="user_id"
            ).execute()
        except Exception as e:
            logger.warning("[InspirationStore] upsert_knowledge_graph failed (FK violation in dev?): %s", e)

    def fetch_knowledge_graph(self, user_id: str) -> Dict[str, Any]:
        """
        Retrieve the stored knowledge graph for a user.
        Returns {} if none exists yet.
        """
        try:
            resp = (
                self.supabase.table("inspiration_knowledge")
                .select("*")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            return resp.data or {}
        except Exception as e:
            logger.warning("[InspirationStore] fetch_knowledge_graph failed: %s", e)
            return {}
