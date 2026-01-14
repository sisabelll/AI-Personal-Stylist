# tests/fixtures.py

# A profile that has just enough keys to satisfy the "ConstraintBuilder"
TEST_PROFILE = {
    "name": "Test User",
    "wear_preference": "Unisex",
    "body_style_essence": "Straight",
    "personal_color": "winter_cool_tone"
}

# Empty rules are fine for the Canary test because we WANT to prove
# that the Stylist relies ONLY on the 'Research' data we inject.
TEST_STYLE_RULES = {
    "personal_color_theory": {},
    "body_style_essence_theory": {},
    "aesthetic_style_summary": {}
}

# A generic, boring context so the Interpreter doesn't get confused
TEST_REQUEST_CONTEXT = {
    "occasion": "Test Event",
    "weather": {
        "temperature_c": 20,
        "conditions": "Clear", 
        "indoor_outdoor": "Indoor"
    },
    "location_context": {
        "city": "Test City",
        "dress_norm": "Casual"
    }
}