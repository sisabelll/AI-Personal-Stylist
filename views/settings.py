"""
Profile settings dialog — lets the user edit their style profile in-app
without re-running the full onboarding flow.
"""
import streamlit as st
from views.onboarding import (
    POPULAR_ICONS,
    POPULAR_BRANDS,
    clean_list,
    compute_color_season,
    compute_body_essence,
    _fetch_all_logos,
    _logo_card_html,
)


def _flat_brands() -> list[str]:
    """All curated brands as a flat list for multiselect."""
    seen = []
    for brands in POPULAR_BRANDS.values():
        for b in brands:
            if b not in seen:
                seen.append(b)
    return seen


@st.dialog("Edit Profile", width="large")
def render_settings(storage, user_id: str):
    profile = st.session_state.get("user_profile") or {}
    prefs   = profile.get("preferences") or {}

    st.markdown("""
    <style>
    /* Tighten dialog spacing */
    div[data-testid="stDialog"] h3 { font-size: 0.72rem; letter-spacing: 0.14em;
        text-transform: uppercase; color: #C9A96E; font-weight: 400; margin-bottom: 0.25rem; }
    div[data-testid="stDialog"] hr { margin: 0.5rem 0 1rem !important; }
    </style>
    """, unsafe_allow_html=True)

    # ── Section 1: Basic info ──────────────────────────────────────────────────
    st.markdown("### About You")
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        full_name = st.text_input("Name", value=profile.get("full_name", ""), key="sp_name")
    with c2:
        location  = st.text_input("City", value=profile.get("location_city", ""), key="sp_city")

    c3, c4 = st.columns(2)
    with c3:
        wear_pref = st.radio(
            "I mostly wear",
            ["Womenswear", "Menswear", "Unisex"],
            index=["Womenswear", "Menswear", "Unisex"].index(
                profile.get("wear_preference", "Womenswear")
            ),
            horizontal=True,
            key="sp_wear",
        )
    with c4:
        budget = st.select_slider(
            "Budget per item",
            options=["$", "$$", "$$$", "$$$$"],
            value=prefs.get("budget_tier", "$$"),
            help="$: <$50 · $$: $50–$150 · $$$: $150–$400 · $$$$: Luxury",
            key="sp_budget",
        )

    # ── Section 2: Color & Body ────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Color & Body")
    st.markdown("---")

    c5, c6 = st.columns(2)
    with c5:
        color_season = st.selectbox(
            "Color Season",
            ["Spring Warm", "Summer Cool", "Autumn Warm", "Winter Cool"],
            index=["Spring Warm", "Summer Cool", "Autumn Warm", "Winter Cool"].index(
                profile.get("color_season", "Summer Cool")
            ),
            key="sp_color_season",
        )
    with c6:
        body_essence = st.selectbox(
            "Body Essence",
            ["Straight", "Wave", "Natural"],
            index=["Straight", "Wave", "Natural"].index(
                profile.get("body_style_essence", "Straight")
            ),
            key="sp_body_essence",
        )

    # ── Section 3: Style Icons ────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Style Icons")
    st.markdown("---")

    current_icons = prefs.get("style_icons") or []
    # Split into known vs custom
    known_selected  = [i for i in current_icons if i in POPULAR_ICONS]
    custom_selected = [i for i in current_icons if i not in POPULAR_ICONS]

    selected_icons = st.multiselect(
        "Popular icons",
        options=POPULAR_ICONS,
        default=known_selected,
        label_visibility="collapsed",
        key="sp_icons_select",
    )
    custom_icons_str = st.text_input(
        "Add more (comma-separated)",
        value=", ".join(custom_selected),
        placeholder="e.g. Jenna Lyons, Tilda Swinton",
        key="sp_icons_custom",
    )

    # ── Section 4: Brands ─────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Favourite Brands")
    st.markdown("---")

    current_brands  = prefs.get("favorite_brands") or []
    all_curated     = _flat_brands()
    known_brands    = [b for b in current_brands if b in all_curated]
    custom_brands_l = [b for b in current_brands if b not in all_curated]

    selected_brands = st.multiselect(
        "Curated brands",
        options=all_curated,
        default=known_brands,
        label_visibility="collapsed",
        key="sp_brands_select",
    )
    custom_brands_str = st.text_input(
        "Add more (comma-separated)",
        value=", ".join(custom_brands_l),
        placeholder="e.g. Ganni, Nanushka, Saks Potts",
        key="sp_brands_custom",
    )

    # ── Section 5: Aesthetic Keywords ─────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Aesthetic")
    st.markdown("---")

    _AESTHETICS = [
        "Minimalist", "Streetwear", "Old Money", "Y2K", "Coquette", "Boho",
        "Corporate Chic", "Athleisure", "Grunge", "Preppy", "Avant-Garde", "Scandi",
    ]
    aesthetics = st.multiselect(
        "Select up to 5",
        _AESTHETICS,
        default=[a for a in (prefs.get("aesthetic_keywords") or []) if a in _AESTHETICS],
        label_visibility="collapsed",
        key="sp_aesthetics",
    )

    # ── Save ───────────────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    col_save, col_cancel = st.columns([2, 1])

    with col_cancel:
        if st.button("Cancel", key="sp_cancel"):
            st.rerun()

    with col_save:
        if st.button("Save Changes", type="primary", key="sp_save"):
            final_icons  = list(dict.fromkeys(selected_icons + clean_list(custom_icons_str)))
            final_brands = list(dict.fromkeys(selected_brands + clean_list(custom_brands_str)))

            profile_payload = {
                "full_name":          full_name.strip().title(),
                "location_city":      location.strip().title(),
                "color_season":       color_season,
                "body_style_essence": body_essence,
                "wear_preference":    wear_pref,
                # preserve existing fields we don't edit here
                "birth_date":  profile.get("birth_date"),
                "height_cm":   profile.get("height_cm"),
                "sizes":       profile.get("sizes") or {},
            }
            prefs_payload = {
                "style_icons":        final_icons,
                "favorite_brands":    final_brands,
                "aesthetic_keywords": aesthetics,
                "budget_tier":        budget,
                "avoid_items":        prefs.get("avoid_items") or [],
            }

            token = (st.session_state.get("session") or {})
            token = token.access_token if hasattr(token, "access_token") else "dev"
            dev_mode = token == "dev" or token == "fake-dev-token"

            try:
                if not dev_mode:
                    storage.save_profile(user_id, profile_payload, prefs_payload, token)
                    new_profile = storage.get_profile(user_id)
                    st.session_state["user_profile"] = new_profile
                else:
                    # Dev mode: update session state directly without hitting Supabase
                    merged = {**profile, **profile_payload, "preferences": {**prefs, **prefs_payload}}
                    st.session_state["user_profile"] = merged

                # Reset conversation so the updated profile takes effect immediately
                st.session_state.pop("manager", None)
                st.session_state.pop("messages", None)
                st.toast("Profile updated ✦")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")
