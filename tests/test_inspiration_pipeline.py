import os
import json
import hashlib
import requests
from core.config import Config
from services.client import OpenAIClient
from agents.inspiration_agent import InspirationAgent
from services.inspiration_store import InspirationStore 
from services.storage import StorageService 

def dedupe_key_from_url(url: str) -> str:
    u = (url or "").strip().lower()
    return hashlib.sha1(u.encode("utf-8")).hexdigest()

def google_cse_image_search(q: str, num: int = 5) -> list[dict]:
    params = {
        "key": Config.GOOGLE_API_KEY,
        "cx": Config.GOOGLE_CSE_ID,
        "q": q,
        "searchType": "image",
        "num": min(num, 10),
        "safe": "active",
    }
    r = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("items") or []

def cse_items_to_inspo_rows(user_id: str, query_meta: dict, cse_items: list[dict]) -> list[dict]:
    out = []
    for it in cse_items:
        image_url = it.get("link")
        page_url = it.get("image", {}).get("contextLink") or it.get("image", {}).get("source") or it.get("displayLink")
        caption = it.get("title")

        if not image_url:
            continue

        # tags derived from provenance (NOT “image understanding”)
        tags = []
        tags.append(query_meta["source_type"])
        tags.append(query_meta["source_name"].lower())
        # crude tokens from query
        tags += [t.lower() for t in query_meta["q"].split()[:6]]

        out.append({
            "source_type": query_meta["source_type"],
            "source_name": query_meta["source_name"],
            "image_url": image_url,
            "page_url": page_url,
            "caption": caption,
            "tags": list(dict.fromkeys([t for t in tags if t]))[:10],
            "score": 0.0,
        })
    return out

def main():
    Config.validate()

    user_id = "dev-user-123"

    client = OpenAIClient()
    agent = InspirationAgent(client)

    storage_service = StorageService() 
    store = InspirationStore(storage_service)

    user_profile = {
        "wear_preference": "womenswear",
        "preferences": {
            "style_icons": ["Bella Hadid", "Sofia Richie Grainge"],
            "favorite_brands": ["The Row", "Khaite", "Toteme"],
        },
    }

    expanded = agent.expand(user_profile)
    queries = agent.build_image_queries(expanded)

    # Keep it cheap: only run a few queries
    queries = queries[:6]

    rows = []
    for qm in queries:
        print(f"\n🔎 CSE: {qm['q']}")
        items = google_cse_image_search(qm["q"], num=5)
        rows += cse_items_to_inspo_rows(user_id, qm, items)

    print(f"\n📦 Prepared rows: {len(rows)}")
    if rows:
        store.upsert_items(user_id, rows)
        print("✅ Upsert done")

    top = store.fetch_top_items(user_id, limit=12)
    print(f"\n🏁 Fetched back: {len(top)}")
    for it in top[:5]:
        print("-", it["source_type"], "|", it["source_name"], "|", it["image_url"][:80])

if __name__ == "__main__":
    main()
