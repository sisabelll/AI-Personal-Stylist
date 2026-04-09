import streamlit as st
from datetime import date
from pathlib import Path
import base64, json, requests, time

# ── Step config ───────────────────────────────────────────────────────────────
STEPS = ["About You", "Measurements", "Color Season", "Style Icons", "Brands & Vibe"]

# ── Preset data ───────────────────────────────────────────────────────────────
POPULAR_BRANDS = {
    "✨ Quiet Luxury":       ["The Row", "Loro Piana", "Brunello Cucinelli", "Toteme", "Lemaire", "Khaite"],
    "⬜ Minimalist / Scandi": ["COS", "Arket", "& Other Stories", "Jil Sander", "Acne Studios", "Uniqlo"],
    "🥐 French / Euro Chic": ["A.P.C.", "Sandro", "Maje", "Isabel Marant", "Jacquemus", "Rouje"],
    "💎 Elevated Fashion":   ["Miu Miu", "Bottega Veneta", "Loewe", "Prada", "Celine", "Dior"],
    "🏙️ Downtown Cool":      ["Aritzia", "Reformation", "Madewell", "Rag & Bone", "Vince", "Frame"],
    "🛹 Street / Sporty":    ["Nike", "New Balance", "Carhartt WIP", "Stüssy", "Sporty & Rich", "Aimé Leon Dore"],
    "🌸 Romantic / Boho":    ["LoveShackFancy", "Sandy Liang", "Zimmermann", "Ulla Johnson", "Selkie", "Chloé"],
    "🎸 Alternative / Edge": ["Rick Owens", "Maison Margiela", "AllSaints", "R13", "Dr. Martens", "Ann Demeulemeester"],
}

# Warm neutral palette — cycled per brand for visual variety
_CARD_COLORS = [
    ("#F5EFE6", "#9B7740"),  # warm cream / gold
    ("#EEF0EC", "#5A6B52"),  # sage / forest
    ("#EDE8F0", "#6B5A7A"),  # lavender / plum
    ("#F0ECE8", "#7A5A4A"),  # blush / terracotta
    ("#E8EEF0", "#4A6B7A"),  # ice blue / steel
    ("#F0EDE8", "#7A6B52"),  # oat / warm brown
]

def _brand_color(brand: str):
    idx = sum(ord(c) for c in brand) % len(_CARD_COLORS)
    return _CARD_COLORS[idx]

BRAND_DOMAINS = {
    "The Row": "therow.com", "Loro Piana": "loropiana.com",
    "Brunello Cucinelli": "brunellocucinelli.com", "Toteme": "toteme-studio.com",
    "Lemaire": "lemaire.fr", "Khaite": "khaite.com",
    "COS": "cos.com", "Arket": "arket.com", "& Other Stories": "stories.com",
    "Jil Sander": "jilsander.com", "Acne Studios": "acnestudios.com", "Uniqlo": "uniqlo.com",
    "A.P.C.": "apc.fr", "Sandro": "sandro-paris.com", "Maje": "maje.com",
    "Isabel Marant": "isabelmarant.com", "Jacquemus": "jacquemus.com", "Rouje": "rouje.com",
    "Miu Miu": "miumiu.com", "Bottega Veneta": "bottegaveneta.com", "Loewe": "loewe.com",
    "Prada": "prada.com", "Celine": "celine.com", "Dior": "dior.com",
    "Aritzia": "aritzia.com", "Reformation": "thereformation.com", "Madewell": "madewell.com",
    "Rag & Bone": "rag-bone.com", "Vince": "vince.com", "Frame": "frame-store.com",
    "Nike": "nike.com", "New Balance": "newbalance.com", "Carhartt WIP": "carhartt-wip.com",
    "Stüssy": "stussy.com", "Sporty & Rich": "sportyandrich.com", "Aimé Leon Dore": "aimeeleondore.com",
    "LoveShackFancy": "loveshackfancy.com", "Sandy Liang": "sandyliang.info",
    "Zimmermann": "zimmermannwear.com", "Ulla Johnson": "ullajohnson.com",
    "Selkie": "selkie.com", "Chloé": "chloe.com",
    "Rick Owens": "rickowens.eu", "Maison Margiela": "maisonmargiela.com",
    "AllSaints": "allsaints.com", "R13": "r13denim.com",
    "Dr. Martens": "drmartens.com", "Ann Demeulemeester": "anndemeulemeester.com",
}

_LOGO_DIR = Path(__file__).parent.parent / "data" / "brand_logos"

@st.cache_data(show_spinner=False)
def _fetch_all_logos() -> dict:
    """Downloads brand logos once per session, caches to disk for instant future loads."""
    _LOGO_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for brand, domain in BRAND_DOMAINS.items():
        slug = "".join(c if c.isalnum() else "_" for c in brand.lower())
        cache_file = _LOGO_DIR / f"{slug}.png"
        # Use disk cache if available
        if cache_file.exists() and cache_file.stat().st_size > 200:
            result[brand] = base64.b64encode(cache_file.read_bytes()).decode()
            continue
        # Try Clearbit, fall back to Google favicon
        for url in [
            f"https://logo.clearbit.com/{domain}",
            f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
        ]:
            try:
                r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and len(r.content) > 200:
                    cache_file.write_bytes(r.content)
                    result[brand] = base64.b64encode(r.content).decode()
                    break
            except Exception:
                continue
    return result

POPULAR_ICONS = [
    "Bella Hadid", "Hailey Bieber", "Zendaya", "Zoë Kravitz", "Kendall Jenner",
    "Emily Ratajkowski", "Dua Lipa", "Sabrina Carpenter", "Sydney Sweeney",
    "Margot Robbie", "Alexa Chung", "Carolyn Bessette-Kennedy", "Kate Moss",
    "Rosé (BLACKPINK)", "Jennie (BLACKPINK)", "Jisoo (BLACKPINK)", "Bae Suzy", "IU",
    "Timothée Chalamet", "A$AP Rocky", "Harry Styles", "Pharrell Williams",
]

# ── Diagnosis helpers ─────────────────────────────────────────────────────────

def compute_color_season(undertone: str, depth: str, clarity: str) -> str:
    if undertone == "Warm":
        return "Spring Warm" if depth in ["Light", "Medium"] else "Autumn Warm"
    elif undertone == "Cool":
        return "Winter Cool" if (depth == "Deep" or clarity == "High") else "Summer Cool"
    else:  # Neutral
        if clarity == "High":
            return "Winter Cool" if depth == "Deep" else "Spring Warm"
        return "Autumn Warm" if depth == "Deep" else "Summer Cool"


def compute_body_essence(bone: str, weight_dist: str, clothes_pref: str) -> str:
    scores = {"Straight": 0, "Wave": 0, "Natural": 0}
    bone_map     = {"Delicate": "Wave",     "Average": "Straight", "Large": "Natural"}
    weight_map   = {"Upper": "Straight",    "Lower": "Wave",       "Evenly": "Natural"}
    clothes_map  = {"Structured": "Straight", "Soft": "Wave",      "Loose": "Natural"}
    for val, mapping in [(bone, bone_map), (weight_dist, weight_map), (clothes_pref, clothes_map)]:
        key = val.split()[0]
        if key in mapping:
            scores[mapping[key]] += 1
    return max(scores, key=scores.get)

# ── Utilities ─────────────────────────────────────────────────────────────────

def clean_text(text):
    if not text:
        return None
    return text.strip() or None

def clean_list(text_input):
    if not text_input:
        return []
    return list(dict.fromkeys(x.strip() for x in text_input.split(",") if x.strip()))

def _parse_height(val: str):
    """Extract the cm integer from e.g. '170 cm  (5\'6\")', or return None."""
    if not val or val == "Prefer not to say":
        return None
    try:
        return int(val.split()[0])
    except (ValueError, IndexError):
        return None

def _clean_size(val):
    """Return None for sentinel/empty values, otherwise the raw string."""
    if not val or val == "Prefer not to say":
        return None
    return val.strip() or None

@st.cache_data(show_spinner=False, ttl=3600)
def _validate_city(city: str) -> bool:
    """Returns True if Open-Meteo geocoding resolves the city to at least one result."""
    try:
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(city)}&count=1"
        r = requests.get(url, timeout=4)
        return bool(r.json().get("results"))
    except Exception:
        return True  # fail open — don't block the user on network issues

def _init():
    if "ob_step" not in st.session_state:
        st.session_state["ob_step"] = 0
    if "ob_selected_brands" not in st.session_state:
        st.session_state["ob_selected_brands"] = set()

def _logo_card_html(brand: str, logos: dict) -> str:
    bg, fg = _brand_color(brand)
    words = [w for w in brand.replace("&", "").replace(".", "").split() if w]
    initials = "".join(w[0] for w in words[:2]).upper()
    b64 = logos.get(brand)
    if b64:
        img_html = (
            f'<img src="data:image/png;base64,{b64}" '
            f'style="width:44px;height:44px;object-fit:contain;'
            f'mix-blend-mode:multiply;display:block;margin:0 auto 4px;">'
        )
    else:
        img_html = (
            f'<div style="width:44px;height:44px;border-radius:8px;background:{bg};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:{"0.95rem" if len(initials)==1 else "0.78rem"};'
            f'font-weight:600;color:{fg};margin:0 auto 4px;">{initials}</div>'
        )
    return f'<div style="text-align:center;">{img_html}</div>'

# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
<style>
/* Progress step labels */
.ob-step-label {
    font-size: 0.68rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #C9A96E;
    margin-bottom: 0.2rem;
}
.ob-step-title {
    font-size: 1.6rem;
    font-family: 'Playfair Display', serif;
    font-weight: 400;
    color: #1C1C1E;
    margin-bottom: 1.5rem;
}

/* Nav buttons */
.ob-nav [data-testid="stButton"] > button {
    border-radius: 8px !important;
}

/* Brand cards: container with border gets card styling */
[data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]) > div {
    padding: 0.75rem 0.5rem !important;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    min-height: 90px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]:checked) > div {
    background: #FDF8F1 !important;
    border-color: #C9A96E !important;
    border-width: 2px !important;
}
/* Hide the raw checkbox mark — keep label clickable */
[data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]) span[data-testid="stMarkdownContainer"] p {
    display: none;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]) [data-testid="stCheckbox"] {
    display: flex !important;
    justify-content: center;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]) [data-testid="stCheckbox"] label {
    font-size: 0.72rem !important;
    color: #5A534E !important;
    cursor: pointer;
    gap: 0 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]) [data-testid="stCheckbox"] input {
    display: none !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]:checked) [data-testid="stCheckbox"] label {
    color: #9B7740 !important;
    font-weight: 500 !important;
}
</style>
"""

# ── Step renderers ────────────────────────────────────────────────────────────

def _step_about():
    st.markdown('<div class="ob-step-label">Step 1 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="ob-step-title">About You</div>', unsafe_allow_html=True)
    error_slot = st.empty()

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Name", placeholder="e.g. Isabel", key="ob_name")
    with c2:
        st.text_input("City", placeholder="e.g. New York, NY", key="ob_city")

    c3, c4 = st.columns(2)
    with c3:
        st.date_input(
            "Birthday",
            min_value=date(1950, 1, 1),
            max_value=date(2015, 12, 31),
            value=date(1995, 6, 15),
            key="ob_birth_date",
        )
    with c4:
        st.radio(
            "I mostly wear",
            ["Womenswear", "Menswear", "Unisex"],
            horizontal=True,
            key="ob_wear_pref",
        )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Next →", type="primary", key="nav_next_0"):
        name = st.session_state.get("ob_name", "").strip()
        city = st.session_state.get("ob_city", "").strip()
        if not name:
            error_slot.error("Please enter your name.")
        elif not city:
            error_slot.error("Please enter your city.")
        else:
            with st.spinner("Checking city…"):
                if not _validate_city(city):
                    error_slot.error(f"We couldn't find "{city}" — please check the spelling or try a nearby city.")
                else:
                    st.session_state["ob_step"] = 1
                    st.rerun()


def _step_measurements():
    st.markdown('<div class="ob-step-label">Step 2 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="ob-step-title">Your Measurements</div>', unsafe_allow_html=True)

    _HEIGHT_OPTIONS = (
        ["Prefer not to say"] +
        [f"{cm} cm  ({int(cm) // 30}'{int(cm) % 30 // 3}\")" for cm in range(148, 201, 1)]
    )
    _SHOE_OPTIONS_W = [
        "Prefer not to say",
        "US 5 / EU 35", "US 5.5 / EU 36", "US 6 / EU 36.5", "US 6.5 / EU 37",
        "US 7 / EU 37.5", "US 7.5 / EU 38", "US 8 / EU 38.5", "US 8.5 / EU 39",
        "US 9 / EU 39.5", "US 9.5 / EU 40", "US 10 / EU 40.5", "US 10.5 / EU 41",
        "US 11 / EU 41.5", "US 11.5 / EU 42",
    ]
    _SHOE_OPTIONS_M = [
        "Prefer not to say",
        "US 6 / EU 39", "US 6.5 / EU 39.5", "US 7 / EU 40", "US 7.5 / EU 40.5",
        "US 8 / EU 41", "US 8.5 / EU 41.5", "US 9 / EU 42", "US 9.5 / EU 42.5",
        "US 10 / EU 43", "US 10.5 / EU 44", "US 11 / EU 44.5", "US 11.5 / EU 45",
        "US 12 / EU 46", "US 13 / EU 47",
    ]
    _BOTTOM_OPTIONS_W = [
        "Prefer not to say",
        "00", "0", "2", "4", "6", "8", "10", "12", "14", "16",
        "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34",
        "XS", "S", "M", "L", "XL", "XXL",
    ]
    _BOTTOM_OPTIONS_M = [
        "Prefer not to say",
        "28×30", "28×32", "30×30", "30×32", "32×30", "32×32", "32×34",
        "34×30", "34×32", "34×34", "36×32", "36×34", "38×32", "38×34",
        "XS", "S", "M", "L", "XL", "XXL",
    ]

    wear_pref = st.session_state.get("ob_wear_pref", "Womenswear")
    # Reset size selections if wear preference changed since last visit
    if st.session_state.get("_ob_last_wear_pref") != wear_pref:
        st.session_state.pop("ob_size_bottom", None)
        st.session_state.pop("ob_size_shoe", None)
        st.session_state["_ob_last_wear_pref"] = wear_pref
    shoe_opts   = _SHOE_OPTIONS_M   if wear_pref == "Menswear" else _SHOE_OPTIONS_W
    bottom_opts = _BOTTOM_OPTIONS_M if wear_pref == "Menswear" else _BOTTOM_OPTIONS_W

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.selectbox("Height", _HEIGHT_OPTIONS, index=22, key="ob_height")  # ~170 cm default
    with c2:
        st.selectbox("Top Size", ["XS", "S", "M", "L", "XL", "XXL"], index=2, key="ob_size_top")
    with c3:
        st.selectbox("Bottom Size", bottom_opts, index=0, key="ob_size_bottom")
    with c4:
        st.selectbox("Shoe Size", shoe_opts, index=0, key="ob_size_shoe")

    st.markdown("---")
    st.markdown("**Body Essence**")
    st.caption("This determines which silhouettes flatter you most. (Based on the Kibbe system.)")

    know_essence = st.toggle("I already know my body essence type", key="ob_know_essence")

    if know_essence:
        st.selectbox(
            "My body essence is:",
            ["Straight — structured, tailored, clean lines",
             "Wave — soft, curved, delicate details",
             "Natural — relaxed, longline, effortless"],
            key="ob_essence_direct",
        )
    else:
        st.radio(
            "🦴 My bone structure feels:",
            ["Delicate & fine — small wrists, narrow or petite frame",
             "Average — moderate size, not very prominent",
             "Large & prominent — visible collarbones/joints, wide or bony"],
            index=None, key="ob_bone_q",
        )
        st.radio(
            "⚖️ If I gain weight, it tends to go to my:",
            ["Upper body — chest, arms, or back look fuller first",
             "Lower body — hips and thighs are fuller than my top",
             "Evenly across my frame — proportional, more skeletal than soft"],
            index=None, key="ob_weight_q",
        )
        st.radio(
            "👗 Clothes look best on me when they're:",
            ["Structured & tailored — clean lines, defined shoulders",
             "Soft & flowy — draped, relaxed, delicate details",
             "Loose & relaxed — oversized, longline, un-fussy"],
            index=None, key="ob_clothes_q",
        )

    # Live preview
    if not know_essence:
        bone_val    = st.session_state.get("ob_bone_q", "")
        weight_val  = st.session_state.get("ob_weight_q", "")
        clothes_val = st.session_state.get("ob_clothes_q", "")
        if bone_val and weight_val and clothes_val:
            preview = compute_body_essence(bone_val, weight_val, clothes_val)
            essence_descriptions = {
                "Straight": "structured, clean lines, tailored silhouettes",
                "Wave":     "soft, curved, delicate and flowy details",
                "Natural":  "relaxed, longline, effortlessly un-fussy",
            }
            st.info(
                f"Based on your answers, you look like a **{preview}** type — "
                f"*{essence_descriptions[preview]}*.",
                icon="💡",
            )

    st.markdown("<br>", unsafe_allow_html=True)
    error_slot = st.empty()
    c_back, _, c_next = st.columns([1, 4, 1])
    with c_back:
        if st.button("← Back", key="nav_back_1"):
            st.session_state["ob_step"] = 0
            st.rerun()
    with c_next:
        if st.button("Next →", type="primary", key="nav_next_1"):
            s = st.session_state
            if not s.get("ob_know_essence"):
                missing = [
                    label for label, key in [
                        ("bone structure", "ob_bone_q"),
                        ("weight distribution", "ob_weight_q"),
                        ("clothing preference", "ob_clothes_q"),
                    ] if not s.get(key)
                ]
                if missing:
                    error_slot.error(f"Please answer all body essence questions: {', '.join(missing)}.")
                    st.stop()
            st.session_state["ob_step"] = 2
            st.rerun()


def _step_color_season():
    st.markdown('<div class="ob-step-label">Step 3 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="ob-step-title">Your Color Season</div>', unsafe_allow_html=True)
    st.caption("Your season tells me which palette makes you glow — and which to avoid.")

    know_season = st.toggle("I already know my color season", key="ob_know_season")

    if know_season:
        st.selectbox(
            "My color season is:",
            ["Spring Warm", "Summer Cool", "Autumn Warm", "Winter Cool"],
            key="ob_season_direct",
        )
    else:
        st.info(
            "**Quick undertone test:** Look at the veins on your inner wrist in natural light.  \n"
            "Greenish → warm · Blue/purple → cool · Both equally → neutral.",
            icon="💡",
        )
        st.radio(
            "🎨 My skin's undertone is:",
            ["Warm — golden, peachy, or olive",
             "Cool — pink, rosy, or slightly bluish",
             "Neutral — I genuinely can't tell"],
            index=None, key="ob_undertone",
        )
        st.radio(
            "🌗 My overall coloring (skin + hair + eyes) is:",
            ["Light — fair skin, light/blonde hair, light eyes",
             "Medium — medium skin, medium-brown or hazel features",
             "Deep — dark/olive skin, dark brown or black hair"],
            index=None, key="ob_depth",
        )
        st.radio(
            "✨ The contrast between my features (hair vs skin vs eyes) is:",
            ["High — sharp contrast, e.g. dark hair + light skin",
             "Low — features blend harmoniously, similar tones"],
            index=None, key="ob_clarity",
        )

    # Live preview
    if not know_season:
        undertone_val = st.session_state.get("ob_undertone", "")
        depth_val     = st.session_state.get("ob_depth", "")
        clarity_val   = st.session_state.get("ob_clarity", "")
        if undertone_val and depth_val and clarity_val:
            ut = undertone_val.split("—")[0].strip()
            dp = depth_val.split("—")[0].strip()
            cl = clarity_val.split("—")[0].strip()
            preview = compute_color_season(ut, dp, cl)
            season_descriptions = {
                "Spring Warm":  "warm, bright, and fresh — golden tones, coral, and warm neutrals",
                "Summer Cool":  "cool, soft, and muted — dusty rose, lavender, and soft grays",
                "Autumn Warm":  "warm, earthy, and deep — terracotta, mustard, and rich browns",
                "Winter Cool":  "cool, clear, and high-contrast — true black, icy tones, jewel hues",
            }
            st.info(
                f"Based on your answers, you look like a **{preview}** — "
                f"*{season_descriptions[preview]}*.",
                icon="🎨",
            )

    st.markdown("<br>", unsafe_allow_html=True)
    error_slot = st.empty()
    c_back, _, c_next = st.columns([1, 4, 1])
    with c_back:
        if st.button("← Back", key="nav_back_2"):
            st.session_state["ob_step"] = 1
            st.rerun()
    with c_next:
        if st.button("Next →", type="primary", key="nav_next_2"):
            s = st.session_state
            if not s.get("ob_know_season"):
                missing = [
                    label for label, key in [
                        ("undertone", "ob_undertone"),
                        ("overall coloring", "ob_depth"),
                        ("feature contrast", "ob_clarity"),
                    ] if not s.get(key)
                ]
                if missing:
                    error_slot.error(f"Please answer all color season questions: {', '.join(missing)}.")
                    st.stop()
            st.session_state["ob_step"] = 3
            st.rerun()


def _step_icons():
    st.markdown('<div class="ob-step-label">Step 4 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="ob-step-title">Style Icons</div>', unsafe_allow_html=True)
    st.caption("Whose wardrobe do you raid in your dreams? Select any that resonate.")

    st.multiselect(
        "Popular icons",
        options=POPULAR_ICONS,
        key="ob_icons_select",
        label_visibility="collapsed",
    )
    st.text_input(
        "Add more (comma-separated)",
        placeholder="e.g. Jenna Lyons, Tilda Swinton, Pharrell Williams",
        key="ob_icons_custom",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    _nav(prev_step=2, next_step=4)


def _step_brands_vibe(storage, user_id):
    st.markdown('<div class="ob-step-label">Step 5 of 5</div>', unsafe_allow_html=True)
    st.markdown('<div class="ob-step-title">Brands & Vibe</div>', unsafe_allow_html=True)
    st.caption("Even aspirationally — which of these feel like *you*?")

    with st.spinner("Loading brand logos…"):
        logos = _fetch_all_logos()

    selected = st.session_state.get("ob_selected_brands", set())

    for category, brands in POPULAR_BRANDS.items():
        st.markdown(f"**{category}**")
        cols = st.columns(6)
        for i, brand in enumerate(brands):
            with cols[i]:
                with st.container(border=True):
                    st.markdown(_logo_card_html(brand, logos), unsafe_allow_html=True)
                    checked = st.checkbox(brand, value=(brand in selected), key=f"ob_brand_{brand}")
                    if checked and brand not in selected:
                        selected.add(brand)
                        st.session_state["ob_selected_brands"] = selected
                    elif not checked and brand in selected:
                        selected.discard(brand)
                        st.session_state["ob_selected_brands"] = selected
        st.markdown("<br>", unsafe_allow_html=True)

    st.text_input(
        "Any others? (comma-separated)",
        placeholder="e.g. Ganni, Nanushka, Saks Potts",
        key="ob_brands_custom",
    )

    st.markdown("---")
    st.markdown("**Your aesthetic keywords**")
    st.multiselect(
        "Select up to 5",
        ["Minimalist", "Streetwear", "Old Money", "Y2K", "Coquette", "Boho",
         "Corporate Chic", "Athleisure", "Grunge", "Preppy", "Avant-Garde", "Scandi"],
        key="ob_aesthetics",
    )

    st.select_slider(
        "Typical budget per item",
        options=["$", "$$", "$$$", "$$$$"],
        value="$$",
        help="$: <$50 · $$: $50–$150 · $$$: $150–$400 · $$$$: Luxury",
        key="ob_budget",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    c_back, _, c_finish = st.columns([1, 4, 2])
    with c_back:
        if st.button("← Back", key="nav_back_4"):
            st.session_state["ob_step"] = 3
            st.rerun()
    with c_finish:
        if st.button("Finish & Style Me ✦", type="primary", key="nav_finish"):
            _save(storage, user_id)


def _nav(prev_step: int, next_step: int):
    c_back, _, c_next = st.columns([1, 4, 1])
    with c_back:
        if st.button("← Back", key=f"nav_back_{prev_step}"):
            st.session_state["ob_step"] = prev_step
            st.rerun()
    with c_next:
        if st.button("Next →", type="primary", key=f"nav_next_{prev_step}"):
            st.session_state["ob_step"] = next_step
            st.rerun()


def _save(storage, user_id):
    s = st.session_state

    # ── Compute / resolve body essence
    if s.get("ob_know_essence"):
        essence_raw = s.get("ob_essence_direct", "Straight — structured, tailored, clean lines")
        body_essence = essence_raw.split("—")[0].strip()
    else:
        body_essence = compute_body_essence(
            s.get("ob_bone_q") or "Average — moderate size, not very prominent",
            s.get("ob_weight_q") or "Evenly across my frame — proportional, more skeletal than soft",
            s.get("ob_clothes_q") or "Structured & tailored — clean lines, defined shoulders",
        )

    # ── Compute / resolve color season
    if s.get("ob_know_season"):
        color_season = s.get("ob_season_direct", "Summer Cool")
    else:
        undertone = (s.get("ob_undertone") or "Neutral — I genuinely can't tell").split("—")[0].strip()
        depth     = (s.get("ob_depth") or "Medium — medium skin, medium-brown or hazel features").split("—")[0].strip()
        clarity   = (s.get("ob_clarity") or "Low — features blend harmoniously, similar tones").split("—")[0].strip()
        color_season = compute_color_season(undertone, depth, clarity)

    # ── Merge icons
    final_icons = list(dict.fromkeys(
        (s.get("ob_icons_select") or []) + clean_list(s.get("ob_icons_custom", ""))
    ))

    # ── Merge brands
    final_brands = list(dict.fromkeys(
        list(s.get("ob_selected_brands", set())) + clean_list(s.get("ob_brands_custom", ""))
    ))

    profile_payload = {
        "full_name":          (clean_text(s.get("ob_name")) or "").title(),
        "birth_date":         str(s.get("ob_birth_date", date(1995, 6, 15))),
        "location_city":      (clean_text(s.get("ob_city")) or "").title(),
        "height_cm":          _parse_height(s.get("ob_height", "")),
        "body_style_essence": body_essence,
        "color_season":       color_season,
        "wear_preference":    s.get("ob_wear_pref", "Womenswear"),
        "sizes": {
            "top":    s.get("ob_size_top", "M"),
            "bottom": _clean_size(s.get("ob_size_bottom")),
            "shoe":   _clean_size(s.get("ob_size_shoe")),
        },
    }

    prefs_payload = {
        "style_icons":        final_icons,
        "favorite_brands":    final_brands,
        "aesthetic_keywords": s.get("ob_aesthetics", []),
        "budget_tier":        s.get("ob_budget", "$$"),
        "avoid_items":        [],
    }

    print(f"DEBUG: Saving Profile for User ID: {user_id}")
    print(f"DEBUG: Profile: {profile_payload}")
    print(f"DEBUG: Prefs: {prefs_payload}")

    token = st.session_state["session"].access_token

    with st.spinner("Creating your profile…"):
        try:
            storage.save_profile(user_id, profile_payload, prefs_payload, token)
            new_profile = storage.get_profile(user_id)
            st.session_state["user_profile"] = new_profile
            st.session_state["profile_complete"] = True
            st.success(
                f"Done! You're a **{color_season}** with a **{body_essence}** essence. "
                "Time to style you. ✦"
            )
            time.sleep(1.5)
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")

# ── Main entry ────────────────────────────────────────────────────────────────

def render_onboarding(storage, user_id):
    if "profile_check_done" not in st.session_state:
        with st.spinner("Checking your account status…"):
            existing_profile = storage.get_profile(user_id)
            if existing_profile:
                st.session_state["user_profile"] = existing_profile
                st.session_state["profile_complete"] = True
                st.session_state["profile_check_done"] = True
                st.rerun()
            else:
                st.session_state["profile_check_done"] = True

    _init()
    st.markdown(_CSS, unsafe_allow_html=True)

    # Progress bar
    step = st.session_state["ob_step"]
    st.progress((step + 1) / len(STEPS))

    st.markdown("<br>", unsafe_allow_html=True)

    if step == 0:
        _step_about()
    elif step == 1:
        _step_measurements()
    elif step == 2:
        _step_color_season()
    elif step == 3:
        _step_icons()
    elif step == 4:
        _step_brands_vibe(storage, user_id)
