from __future__ import annotations
from typing import List, Optional
from services.storage import StorageService
from core.schemas import TrendCard, WearPreference

# Maps display color season labels to TrendCard.color_overrides attribute names
_COLOR_SEASON_KEY = {
    "spring warm": "spring_warm",
    "summer cool": "summer_cool",
    "autumn warm": "autumn_warm",
    "winter cool": "winter_cool",
}

class TrendsRetriever:
    def __init__(self, storage: StorageService):
        self.supabase = storage.supabase

    def fetch_recent(
        self,
        *,
        season: str,
        wear_pref: WearPreference,
        limit: int = 40,
    ) -> List[TrendCard]:
        """
        Cheap baseline: pull latest trends for season + wear scope.
        We'll rank locally using context keywords (next step).
        """
        # allow unisex for everyone; unisex pref sees all
        if wear_pref == "unisex":
            scopes = ["womenswear", "menswear", "unisex"]
        else:
            scopes = [wear_pref, "unisex"]

        resp = (
            self.supabase
            .table("trend_cards")
            .select("*")
            .eq("season", season)
            .in_("wear_scope", scopes)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )

        rows = resp.data or []
        out: List[TrendCard] = []
        for r in rows:
            try:
                out.append(TrendCard.model_validate(r))
            except Exception:
                continue
        return out
    def fetch_relevant(
        self,
        *,
        season: str,
        wear_pref: WearPreference,
        context_terms: Optional[List[str]] = None,
        fetch_limit: int = 40,
        top_k: int = 8,
        body_essence: Optional[str] = None,
        color_season: Optional[str] = None,
    ) -> List[TrendCard]:
        """Pulls recent trends and applies personalized local ranking."""
        trends = self.fetch_recent(season=season, wear_pref=wear_pref, limit=fetch_limit)
        return simple_rank(trends, context_terms or [], top_k=top_k,
                           body_essence=body_essence, color_season=color_season)
    
def simple_rank(
    trends: List[TrendCard],
    context_terms: List[str],
    top_k: int = 8,
    body_essence: Optional[str] = None,
    color_season: Optional[str] = None,
) -> List[TrendCard]:
    """
    Rank trends by keyword overlap, boosted by personalized body/color overrides.
    Falls back to confidence-ordered list when no context terms are provided.
    """
    terms = {t.strip().lower() for t in context_terms if t and t.strip()}
    color_key = _COLOR_SEASON_KEY.get((color_season or "").lower())

    scored = []
    for c in trends:
        # Keyword overlap score
        hay = " ".join((c.keywords or []) + (c.signals or []) + [c.trend_name or ""]).lower()
        score = sum(1 for t in terms if t in hay) if terms else 0

        # Bonus when the card has a personalized override for the user's body essence
        if body_essence and body_essence in ("straight", "wave", "natural"):
            ov = getattr(c.essence_overrides, body_essence, None)
            if ov and (ov.best_versions or ov.styling_notes):
                score += 2

        # Bonus when the card has a personalized override for the user's color season
        if color_key:
            ov = getattr(c.color_overrides, color_key, None)
            if ov and (ov.best_colors or ov.styling_notes):
                score += 2

        scored.append((score, c.confidence or 0.0, c))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [c for _, _, c in scored[:top_k]]


def build_trend_context_pack(
    trends: List[TrendCard],
    *,
    max_cards: int = 6,
    body_essence: Optional[str] = None,
    color_season: Optional[str] = None,
) -> dict:
    """
    Compress top trend cards into a prompt-ready dict.
    Includes personalized essence/color overrides when available.
    Source URLs are excluded — they're meaningless to the stylist LLM.
    """
    color_key = _COLOR_SEASON_KEY.get((color_season or "").lower())
    cards = []
    for c in trends[:max_cards]:
        card: dict = {
            "trend_name": c.trend_name,
            "signals": (c.signals or [])[:4],
            "what_to_borrow": (c.what_to_borrow or [])[:3],
            "avoid": (c.avoid or [])[:2],
            "confidence": round(c.confidence or 0.0, 2),
        }

        if body_essence and body_essence in ("straight", "wave", "natural"):
            ov = getattr(c.essence_overrides, body_essence, None)
            if ov and (ov.best_versions or ov.styling_notes):
                card["for_your_body_essence"] = {
                    "best_versions": ov.best_versions[:3],
                    "styling_notes": ov.styling_notes[:2],
                }

        if color_key:
            ov = getattr(c.color_overrides, color_key, None)
            if ov and (ov.best_colors or ov.styling_notes):
                card["for_your_color_season"] = {
                    "best_colors": ov.best_colors[:3],
                    "styling_notes": ov.styling_notes[:2],
                }

        cards.append(card)
    return {"trend_cards": cards}