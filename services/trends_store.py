# services/trends_store.py
from __future__ import annotations

from typing import Dict, List
from datetime import datetime, timezone

from core.schemas import TrendCard
from core.trends import dedupe_list
from services.trend_source_cache import canonicalize_url

def dedupe_urls(urls: List[str], cap: int) -> List[str]:
        seen = set()
        out = []
        for u in urls:
            if not u:
                continue
            cu = canonicalize_url(u)
            if not cu or cu in seen:
                continue
            seen.add(cu)
            out.append(cu)
            if len(out) >= cap:
                break
        return out

class TrendsStore:
    def __init__(self, storage_service):
        self.supabase = storage_service.supabase

    def load_alias_map(self) -> Dict[str, str]:
        try:
            resp = self.supabase.table("trend_aliases").select("alias,canonical").execute()
            rows = resp.data or []
            return {r["alias"]: r["canonical"] for r in rows if r.get("alias") and r.get("canonical")}
        except Exception:
            return {}

    def fetch_by_keys(self, keys: List[str]) -> Dict[str, TrendCard]:
        if not keys:
            return {}
        resp = self.supabase.table("trend_cards").select("*").in_("trend_key", keys).execute()
        rows = resp.data or []
        out: Dict[str, TrendCard] = {}
        for r in rows:
            try:
                out[r["trend_key"]] = TrendCard.model_validate(r)
            except Exception:
                continue
        return out
    
    def merge(self, existing: TrendCard, incoming: TrendCard) -> TrendCard:
        merged = existing.model_copy(deep=True)

        merged.signals = dedupe_list([*existing.signals, *incoming.signals], 10)
        merged.keywords = dedupe_list([*existing.keywords, *incoming.keywords], 25)
        merged.what_to_borrow = dedupe_list([*existing.what_to_borrow, *incoming.what_to_borrow], 6)
        merged.avoid = dedupe_list([*existing.avoid, *incoming.avoid], 6)
        merged.sources = dedupe_urls([*existing.sources, *incoming.sources], 10)

        merged.confidence = max(existing.confidence, incoming.confidence)
        if incoming.shelf_life_weeks and 1 <= incoming.shelf_life_weeks <= 52:
            merged.shelf_life_weeks = incoming.shelf_life_weeks

        eo = merged.essence_overrides
        for k in ("straight", "wave", "natural"):
            prev = getattr(existing.essence_overrides, k)
            newv = getattr(incoming.essence_overrides, k)

            setattr(eo, k, prev.model_copy(update={
                "best_versions": dedupe_list([*prev.best_versions, *newv.best_versions], 8),
                "avoid_versions": dedupe_list([*prev.avoid_versions, *newv.avoid_versions], 8),
                "styling_notes": dedupe_list([*prev.styling_notes, *newv.styling_notes], 8),
            }))
        merged.essence_overrides = eo

        co = merged.color_overrides
        for k in ("spring_warm", "summer_cool", "autumn_warm", "winter_cool"):
            prev = getattr(existing.color_overrides, k)
            newv = getattr(incoming.color_overrides, k)

            setattr(co, k, prev.model_copy(update={
                "best_colors": dedupe_list([*prev.best_colors, *newv.best_colors], 10),
                "avoid_colors": dedupe_list([*prev.avoid_colors, *newv.avoid_colors], 10),
                "styling_notes": dedupe_list([*prev.styling_notes, *newv.styling_notes], 8),
            }))
        merged.color_overrides = co
        return merged

    def upsert(self, cards: List[TrendCard]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload = []
        for c in cards:
            row = c.model_dump()
            row["updated_at"] = now
            payload.append(row)

        self.supabase.table("trend_cards").upsert(payload).execute()

