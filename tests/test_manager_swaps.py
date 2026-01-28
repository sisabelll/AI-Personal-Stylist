import sys
import types
import pytest

# Provide a minimal streamlit stub if not installed.
try:
    import streamlit  # noqa: F401
except Exception:
    stub = types.ModuleType("streamlit")
    def _cache_data(**_kwargs):
        def _decorator(fn):
            return fn
        return _decorator
    stub.cache_data = _cache_data
    sys.modules["streamlit"] = stub

from workflow import manager as manager_module
from workflow.manager import ConversationManager


def make_item(category: str, name: str):
    return {"category": category, "item_name": name, "search_query": f"{name} query", "reason": "test"}


def make_outfit(items):
    return {"outfit_options": [{"items": items}]}


def make_manager():
    user_profile = {
        "id": "test",
        "preferences": {},
        "wear_preference": "Unisex",
        "body_style_essence": "straight",
        "personal_color": "winter_cool_tone",
    }
    style_rules = {"personal_color_theory": {}, "body_style_essence_theory": {}, "aesthetic_style_summary": {}}
    class DummyCatalogClient:
        def search_products_parallel(self, items):
            return {}

    manager_module.CatalogClient = DummyCatalogClient
    return ConversationManager(client=None, user_profile=user_profile, style_rules=style_rules, storage=None, dev_mode=True)


def test_swap_to_onepiece_forbids_top_bottom():
    manager = make_manager()
    current_items = [make_item("Top", "Old Top"), make_item("Bottom", "Old Bottom")]
    outfit = make_outfit([make_item("OnePiece", "New Dress")])
    res = manager._check_swap_requirements(outfit, current_items, ["OnePiece"])
    assert res["missing"] == []
    assert res["forbidden"] == []


def test_swap_to_bottom_requires_top_bottom_and_forbids_onepiece():
    manager = make_manager()
    current_items = [make_item("OnePiece", "Old Dress")]
    outfit = make_outfit([make_item("Bottom", "New Skirt"), make_item("Top", "New Sweater")])
    res = manager._check_swap_requirements(outfit, current_items, ["Bottom"])
    assert res["missing"] == []
    assert res["forbidden"] == []


def test_swap_to_bottom_missing_top_is_flagged():
    manager = make_manager()
    current_items = [make_item("OnePiece", "Old Dress")]
    outfit = make_outfit([make_item("Bottom", "New Skirt")])
    res = manager._check_swap_requirements(outfit, current_items, ["Bottom"])
    assert res["missing"] == ["Top"]
    assert res["forbidden"] == []


def test_swap_non_structural_category_required():
    manager = make_manager()
    current_items = [make_item("Top", "Old Top"), make_item("Bottom", "Old Bottom")]
    outfit = make_outfit([make_item("Top", "New Top"), make_item("Bottom", "New Bottom"), make_item("Shoes", "New Shoes")])
    res = manager._check_swap_requirements(outfit, current_items, ["Shoes"])
    assert res["missing"] == []
    assert res["forbidden"] == []
    assert res["unchanged"] == []


def test_swap_unchanged_is_flagged():
    manager = make_manager()
    current_items = [make_item("Shoes", "Old Shoes")]
    outfit = make_outfit([make_item("Shoes", "Old Shoes")])
    res = manager._check_swap_requirements(outfit, current_items, ["Shoes"], ["Shoes"])
    assert res["missing"] == []
    assert res["forbidden"] == []
    assert res["unchanged"] == ["Shoes"]
