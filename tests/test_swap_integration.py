import sys
import types
import unittest

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
from agents.stylist import StyleStylist


class TestSwapIntegration(unittest.TestCase):
    def make_manager(self):
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

    def test_expand_swap_set_preserves_raw_intent(self):
        manager = self.make_manager()
        old_cats = {"OnePiece", "Shoes"}
        raw_set = {"Bottom"}
        expanded = manager._expand_swap_set(old_cats, raw_set)
        self.assertEqual(raw_set, {"Bottom"})
        self.assertEqual(expanded, {"Bottom", "OnePiece", "Top"})

    def test_stylist_prefers_raw_swaps(self):
        stylist = StyleStylist(client=None)
        feedback = {"swap_out_raw": ["Bottom"], "swap_out": ["Bottom", "OnePiece", "Top"]}
        raw = stylist._get_swap_requests_raw(feedback)
        self.assertEqual(raw, ["Bottom"])


if __name__ == "__main__":
    unittest.main()
