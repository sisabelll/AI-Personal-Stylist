"""
Debug script: test inspiration board fetch + load for an existing user.
Usage: PYTHONPATH=. python scripts/debug_inspo_board.py
"""
import os
import sys

USER_ID = "61f1166f-a40b-423d-ad7a-40c32f246789"

from services.storage import StorageService
from services.inspiration_store import InspirationStore

storage = StorageService()
store = InspirationStore(storage)

print("=" * 60)
print("1. KNOWLEDGE GRAPH")
print("=" * 60)
kg = store.fetch_knowledge_graph(USER_ID)
if not kg:
    print("❌ No KG row found — user will be treated as new")
else:
    print(f"✅ last_refreshed_at : {kg.get('last_refreshed_at')}")
    print(f"   similar_icons     : {len(kg.get('similar_icons') or [])} entries")
    print(f"   motifs            : {len(kg.get('motifs') or [])} entries")
    print(f"   brand_angles      : {len(kg.get('brand_angles') or [])} entries")

print()
print("=" * 60)
print("2. INSPIRATION ITEMS (raw fetch, limit 10)")
print("=" * 60)
items = store.fetch_top_items(user_id=USER_ID, limit=10)
print(f"{'✅' if items else '❌'} fetch_top_items returned {len(items)} items")
for i, it in enumerate(items[:3]):
    print(f"  [{i}] source={it.get('source_name')} | score={it.get('score')} | feedback={it.get('feedback')} | url={it.get('image_url','')[:60]}")

print()
print("=" * 60)
print("3. TOTAL ITEM COUNT (limit 400)")
print("=" * 60)
all_items = store.fetch_top_items(user_id=USER_ID, limit=400)
print(f"Total items in pool: {len(all_items)}")
from collections import Counter
by_source = Counter(it.get("source_type") for it in all_items)
print(f"By source_type: {dict(by_source)}")
by_feedback = Counter(it.get("feedback") for it in all_items)
print(f"By feedback: {dict(by_feedback)}")
