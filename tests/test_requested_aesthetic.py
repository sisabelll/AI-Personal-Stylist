import sys
import types
import unittest

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

from agents.interpreter import resolve_aesthetic_guidelines
from agents.stylist import StyleStylist
from core.schemas import StyleInterpretation
from workflow import manager as manager_module
from workflow.manager import ConversationManager

STREETWEAR = {
    "vibe": "Rooted in youth culture.",
    "keywords": ["oversized", "sneakers", "hoodie"],
    "key_brands": ["Stussy", "Carhartt WIP"],
    "fabric_focus": "Heavyweight jersey, fleece.",
}
STYLE_RULES = {
    "personal_color_theory": {},
    "body_style_essence_theory": {},
    "aesthetic_style_summary": {"Streetwear": STREETWEAR, "Old Money": {"vibe": "Inherited wealth."}},
}


class _PromptCapture(Exception):
    pass


class _CapturingClient:
    def __init__(self):
        self.system_prompt = None

    def call_api(self, model, messages, **_kwargs):
        self.system_prompt = messages[0]["content"]
        raise _PromptCapture()


def make_manager(preferences=None):
    class DummyCatalogClient:
        def search_products_parallel(self, items):
            return {}

    manager_module.CatalogClient = DummyCatalogClient
    profile = {"id": "t", "preferences": preferences or {}, "wear_preference": "Unisex"}
    return ConversationManager(client=None, user_profile=profile, style_rules=STYLE_RULES, storage=None, dev_mode=True)


def capture_prompt(constraints, signals):
    client = _CapturingClient()
    try:
        StyleStylist(client).recommend(constraints=constraints, situational_signals=signals, user_query="q")
    except _PromptCapture:
        pass
    return client.system_prompt


class TestResolveAestheticGuidelines(unittest.TestCase):
    def test_matches_style_rules_keys_regardless_of_spelling(self):
        self.assertEqual(resolve_aesthetic_guidelines(STYLE_RULES, "streetwear"), ("Streetwear", STREETWEAR))
        self.assertEqual(resolve_aesthetic_guidelines(STYLE_RULES, "old_money")[0], "Old Money")

    def test_unknown_or_missing_aesthetic_resolves_to_nothing(self):
        self.assertEqual(resolve_aesthetic_guidelines(STYLE_RULES, "edgy"), (None, {}))
        self.assertEqual(resolve_aesthetic_guidelines(STYLE_RULES, None), (None, {}))


class TestSchemaCanCarryStreetwear(unittest.TestCase):
    def test_streetwear_is_a_valid_aesthetic_bias(self):
        interp = StyleInterpretation(reasoning_steps=[], aesthetic_bias="streetwear", aesthetic_explicit=True)
        self.assertEqual(interp.aesthetic_bias, "streetwear")


class TestManagerPassesRequestedAesthetic(unittest.TestCase):
    def test_explicit_aesthetic_reaches_signals_with_its_guide(self):
        m = make_manager()
        m.current_context = {"aesthetic_bias": "streetwear", "aesthetic_explicit": True}
        signals = m._base_signals()
        self.assertEqual(signals["requested_aesthetic"], "Streetwear")
        self.assertEqual(signals["aesthetic_guidelines"], STREETWEAR)

    def test_inferred_aesthetic_is_not_treated_as_a_request(self):
        m = make_manager()
        m.current_context = {"aesthetic_bias": "streetwear", "aesthetic_explicit": False}
        self.assertNotIn("requested_aesthetic", m._base_signals())

    def test_profile_aesthetic_guide_is_resolved_from_snake_case(self):
        m = make_manager(preferences={"aesthetic_keywords": ["streetwear"]})
        self.assertEqual(m._enriched_profile["aesthetic_guidelines"], STREETWEAR)


class TestStylistPrompt(unittest.TestCase):
    def test_requested_aesthetic_block_leads_and_reframes_body_rules(self):
        prompt = capture_prompt(
            constraints={"body_style_essence": "straight", "body_guidelines": {"type_name": "Straight"}},
            signals={
                "requested_aesthetic": "Streetwear",
                "aesthetic_guidelines": STREETWEAR,
                "style_interpretation": {"formality_level": "low"},
            },
        )
        self.assertIn("REQUESTED AESTHETIC — Streetwear", prompt)
        self.assertIn("Carhartt WIP", prompt)
        self.assertLess(prompt.index("REQUESTED AESTHETIC"), prompt.index("CONTEXT"))
        self.assertIn("within the Streetwear aesthetic", prompt)
        self.assertNotIn("refined staples", prompt)

    def test_profile_aesthetic_is_guidance_only(self):
        prompt = capture_prompt(constraints={"aesthetic_guidelines": STREETWEAR}, signals={})
        self.assertIn("AESTHETIC LANE", prompt)
        self.assertNotIn("REQUESTED AESTHETIC", prompt)


if __name__ == "__main__":
    unittest.main()
