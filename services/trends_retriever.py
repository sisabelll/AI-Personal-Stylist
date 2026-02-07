from __future__ import annotations
from typing import List, Optional
from services.storage import StorageService
from core.schemas import TrendCard, WearPreference

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
    ) -> List[TrendCard]:
        """
        Compatibility + convenience:
        - pulls recent trends
        - applies local deterministic rank
        """
        trends = self.fetch_recent(season=season, wear_pref=wear_pref, limit=fetch_limit)
        return simple_rank(trends, context_terms or [], top_k=top_k)
    
def simple_rank(trends: List[TrendCard], context_terms: List[str], top_k: int = 8) -> List[TrendCard]:
    """
    Local ranking: score by overlap with keywords/signals.
    Keep deterministic and cheap.
    """
    terms = {t.strip().lower() for t in context_terms if t and t.strip()}
    if not terms:
        return trends[:top_k]

    scored = []
    for c in trends:
        hay = " ".join((c.keywords or []) + (c.signals or []) + [c.trend_name or ""]).lower()
        score = sum(1 for t in terms if t in hay)
        scored.append((score, c.confidence or 0.0, c))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [c for _, _, c in scored[:top_k]]

def build_trend_context_pack(trends: List[TrendCard], *, max_cards: int = 6) -> dict:
    cards = []
    for c in trends[:max_cards]:
        cards.append({
            "trend_name": c.trend_name,
            "signals": (c.signals or [])[:4],
            "what_to_borrow": (c.what_to_borrow or [])[:3],
            "avoid": (c.avoid or [])[:2],
            "confidence": c.confidence,
            "sources": (c.sources or [])[:2],
        })
    return {"trend_cards": cards}