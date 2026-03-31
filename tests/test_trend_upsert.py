from __future__ import annotations

from services.storage import StorageService
from services.trends_store import TrendsStore
from core.schemas import TrendCard
from core.trends import compute_trend_key, normalize_trend_name
from dotenv import load_dotenv

load_dotenv()

def make_card(season: str, name: str) -> TrendCard:
    canonical = normalize_trend_name(name)
    trend_key = compute_trend_key(season, "micro", canonical)

    return TrendCard(
        trend_key=trend_key,
        season=season,
        trend_type="micro",
        wear_scope="womenswear",

        canonical_name=canonical,
        trend_name=name,

        signals=["Polished flat shoes with almond toe", "Sleek longline blazer"],
        keywords=["polished flats", "longline blazer", "clean tailoring"],
        what_to_borrow=["Swap sneakers for refined flats", "Try a longer blazer proportion"],
        avoid=["Chunky dad sneakers"],
        sources=["https://example.com/source-a"],

        # these must match your strict schema shape
        essence_overrides={
            "straight": {"best_versions": [], "avoid_versions": [], "styling_notes": []},
            "wave": {"best_versions": [], "avoid_versions": [], "styling_notes": []},
            "natural": {"best_versions": [], "avoid_versions": [], "styling_notes": []},
        },
        color_overrides={
            "spring_warm": {"best_colors": [], "avoid_colors": [], "styling_notes": []},
            "summer_cool": {"best_colors": [], "avoid_colors": [], "styling_notes": []},
            "autumn_warm": {"best_colors": [], "avoid_colors": [], "styling_notes": []},
            "winter_cool": {"best_colors": [], "avoid_colors": [], "styling_notes": []},
        },

        confidence=0.7,
        shelf_life_weeks=12,
    )

def main():
    storage = StorageService()
    store = TrendsStore(storage)

    # 1) Insert two distinct cards
    cards = [
        make_card("2026", "Polished Flats Revival"),
        make_card("2026", "Soft-Volume Skirts"),
    ]
    store.upsert(cards)
    print("✅ Upserted 2 cards")

    # 2) Upsert again with same trend_key to test conflict update path
    updated = make_card("2026", "Polished Flats Revival")
    updated.signals.append("Glossy leather + minimal hardware")
    updated.confidence = 0.9
    store.upsert([updated])
    print("✅ Upserted 1 card (conflict update)")

    # 3) Fetch by keys to confirm
    got = store.fetch_by_keys([c.trend_key for c in cards])
    for k, v in got.items():
        print("-----")
        print("trend_key:", k)
        print("trend_name:", v.trend_name)
        print("confidence:", v.confidence)
        print("signals:", v.signals)

if __name__ == "__main__":
    main()
