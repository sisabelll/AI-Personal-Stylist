import json
import os
import streamlit as st
import requests
import traceback
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import urlopen
from dotenv import load_dotenv

# --- SERVICES & AGENTS ---
from services.storage import StorageService
from services.catalog import CatalogClient
from services.client import OpenAIClient
from services.inspiration_store import InspirationStore
from workflow.manager import ConversationManager

# --- VIEWS ---
from views.login import render_login
from views.onboarding import render_onboarding
from views.settings import render_settings

# --- COMPONENTS ---
from components.inspiration_board import inspiration_board as inspo_board_component
from components.chat_status import chat_status
import streamlit.components.v1 as st_components

# --- CONFIG ---
load_dotenv()
st.set_page_config(page_title="AI Personal Stylist", page_icon="✦", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;1,400&family=DM+Sans:wght@300;400;500&display=swap');

/* ── BASE ─────────────────────────────────────────────── */
html, body, .stApp {
    background-color: #FAF8F4 !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* ── SIDEBAR ─────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #1A1A1A !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label {
    color: #B8AFA8 !important;
    font-family: 'DM Sans', sans-serif !important;
}
[data-testid="stSidebar"] hr {
    border-color: #2E2E2E !important;
    opacity: 1 !important;
}
/* Target only user-rendered buttons (Log Out), not Streamlit chrome buttons */
[data-testid="stSidebar"] [data-testid="stButton"] > button {
    background: transparent !important;
    border: 1px solid #3A3A3A !important;
    color: #B8AFA8 !important;
    border-radius: 6px !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.06em !important;
    font-family: 'DM Sans', sans-serif !important;
    width: auto !important;
    padding: 0.3rem 1.2rem !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button:hover {
    border-color: #C9A96E !important;
    color: #C9A96E !important;
    background: transparent !important;
}
/* Hide all Streamlit chrome we don't want */
[data-testid="stToolbarActions"],
[data-testid="stStatusWidget"],
[data-testid="stSidebarCollapseButton"],
button[aria-label="Keyboard shortcuts"],
button[aria-label*="keyboard" i],
button[aria-label*="collapse" i],
[data-testid="stKeyboardShortcutsHelpModal"] {
    display: none !important;
}

/* ── PAGE HEADER ──────────────────────────────────────── */
.stylist-header {
    padding: 1.25rem 0 1.25rem 0;
    border-bottom: 1px solid #E5DDD5;
    margin-bottom: 1.75rem;
}
.header-eyebrow {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.67rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #C9A96E;
    margin-bottom: 0.5rem;
}
.header-title {
    font-family: 'Playfair Display', serif;
    font-size: 2.3rem;
    font-weight: 400;
    color: #1C1C1E;
    line-height: 1.15;
    margin: 0;
}
.header-meta {
    font-size: 0.72rem;
    color: #9C9590;
    letter-spacing: 0.05em;
    margin-top: 0.5rem;
}

/* ── TABS ─────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0 !important;
    background: transparent !important;
    border-bottom: 1px solid #E5DDD5 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.7rem !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    color: #9C9590 !important;
    background: transparent !important;
    border-bottom: 2px solid transparent !important;
    padding: 0.65rem 1.5rem !important;
    margin-right: 0.25rem;
}
.stTabs [aria-selected="true"] {
    color: #1C1C1E !important;
    border-bottom: 2px solid #C9A96E !important;
    background: transparent !important;
}

/* ── CHAT MESSAGES ────────────────────────────────────── */
/* Strip Streamlit's default card from all messages */
[data-testid="stChatMessage"] {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 0 !important;
    margin-bottom: 0.1rem !important;
    box-shadow: none !important;
}

/* Hide chat avatars — cover both old and new Streamlit testid names */
[data-testid="chatAvatarIcon-user"],
[data-testid="chatAvatarIcon-assistant"],
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"],
[data-testid="stChatMessage"] img[alt="user avatar"],
[data-testid="stChatMessage"] img[alt="assistant avatar"] {
    display: none !important;
}

/* User bubble — right-aligned, warm ivory */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) > div {
    flex-direction: row-reverse !important;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) .stMarkdown {
    background: #F5EFE6 !important;
    border-radius: 16px 16px 4px 16px !important;
    padding: 0.7rem 1rem !important;
    max-width: 72% !important;
    margin-left: auto !important;
    color: #3A3530 !important;
}

/* Assistant response — left-aligned, thin gold rule */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
    border-left: 2px solid #E5DDD5 !important;
    padding-left: 1.1rem !important;
    margin-bottom: 1.25rem !important;
    margin-top: 0.5rem !important;
}

/* ── CHAT INPUT (native, pinned to bottom) ────────────── */
[data-testid="stChatInput"] {
    background: #FAF8F4 !important;
    padding: 0.6rem 0 0.5rem !important;
    border-top: 1px solid #EDE8E2 !important;
}
[data-testid="stChatInput"] > div {
    border: 1px solid #DDD6CE !important;
    border-radius: 14px !important;
    background: #FFFFFF !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05) !important;
}
[data-testid="stChatInput"] textarea {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.88rem !important;
    color: #3A3530 !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: #C2BAB3 !important;
    font-style: italic;
}
/* Send button inside native chat input */
[data-testid="stChatInput"] button {
    background: #C9A96E !important;
    border-radius: 50% !important;
    color: #fff !important;
}
[data-testid="stChatInput"] button:hover {
    background: #B8924F !important;
}

/* ── BUTTONS ──────────────────────────────────────────── */
div[data-testid="stButton"] > button,
a[data-testid="stLinkButton"] > button {
    padding: 0.3rem 0.75rem !important;
    font-size: 0.78rem !important;
    font-family: 'DM Sans', sans-serif !important;
    letter-spacing: 0.05em !important;
    border-radius: 8px !important;
    border: 1px solid #DDD6CE !important;
    background: #FFFFFF !important;
    color: #3A3530 !important;
    transition: all 0.15s ease !important;
}
div[data-testid="stButton"] > button:hover {
    border-color: #C9A96E !important;
    color: #9B7740 !important;
    background: #FDF8F1 !important;
}

/* ── CONTAINERS & CARDS ───────────────────────────────── */
/* Scoped to main content only — sidebar must not inherit card styling */
section.main div[data-testid="stVerticalBlock"] { gap: 0.6rem; }
section.main [data-testid="stVerticalBlockBorderWrapper"] > div {
    border: 1px solid #EDE8E2 !important;
    border-radius: 12px !important;
    background: #FFFFFF !important;
}

/* Sidebar expander — match dark theme */
[data-testid="stSidebar"] [data-testid="stExpander"] {
    border: 1px solid #2E2E2E !important;
    border-radius: 8px !important;
    background: transparent !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #6A6560 !important;
    font-size: 0.74rem !important;
    letter-spacing: 0.05em !important;
}

/* ── PROGRESS BAR ─────────────────────────────────────── */
[data-testid="stProgressBar"] > div {
    background: #EDE8E2 !important;
    border-radius: 99px !important;
    height: 4px !important;
}
[data-testid="stProgressBar"] > div > div {
    background: linear-gradient(90deg, #C9A96E, #E2C898) !important;
    border-radius: 99px !important;
}

/* ── HEADINGS & TYPOGRAPHY ────────────────────────────── */
h1, h2, h3 {
    font-family: 'Playfair Display', serif !important;
    font-weight: 400 !important;
    color: #1C1C1E !important;
    letter-spacing: -0.01em;
}
[data-testid="stCaptionContainer"] p {
    font-size: 0.76rem !important;
    color: #9C9590 !important;
    letter-spacing: 0.02em;
}

/* ── DIVIDERS ─────────────────────────────────────────── */
hr {
    border-color: #EDE8E2 !important;
    margin: 0.75rem 0 !important;
}
</style>
""", unsafe_allow_html=True)

if "storage" not in st.session_state:
    st.session_state["storage"] = StorageService()

storage = st.session_state["storage"]
if "inspo_store" not in st.session_state:
    st.session_state["inspo_store"] = InspirationStore(storage)

inspo_store = st.session_state["inspo_store"]

# ==========================================
# 🛠️ DEV MODE: BYPASS LOGIN
# ==========================================
# Set this to True to skip login. Set to False for production.
DEV_MODE = False
DEV_SHOW_ONBOARDING = False  # set True to test the onboarding form

if DEV_MODE and "user" not in st.session_state:
    # 1. Mock the User Object (What Supabase usually gives you)
    class MockUser:
        def __init__(self):
            self.id = "00000000-0000-0000-0000-000000000001"
            self.email = "isabel@dev.com"

    # 2. Mock the Session Object (So code asking for tokens doesn't crash)
    class MockSession:
        def __init__(self):
            self.access_token = "fake-dev-token"
            self.user = MockUser()

    # 3. Inject into Streamlit State
    st.session_state["user"] = MockUser()
    st.session_state["user_id"] = "00000000-0000-0000-0000-000000000001"
    st.session_state["session"] = MockSession()
    
    # 4. Mock the Database Profile
    st.session_state["user_profile"] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "full_name": "Isabel Dev",
        "location_city": "New York",
        "color_season": "Summer Cool",
        "body_style_essence": "Straight",
        "wear_preference": "Womenswear",
        "preferences": {
            "aesthetic_keywords": ["Minimalist", "Streetwear"],
            "style_icons": ["Bella Hadid"],
            "favorite_brands": ["Arket", "The Row"],
            "budget_tier": "$$"
        }
    }
    
    # 5. Mark Profile as Complete (Skips the Onboarding Form)
    if not DEV_SHOW_ONBOARDING:
        st.session_state["profile_complete"] = True

# =========================================================
# 1. AUTHENTICATION & SESSION MANAGEMENT
# =========================================================
if "ux_events" not in st.session_state:
    st.session_state.ux_events = []

def ux_callback(event):
    st.session_state.ux_events.append(event)

# --- Cookie-based session persistence ---
# We write cookies via JavaScript (runs in the browser, synchronous and reliable)
# and read them via st.context.cookies (reads HTTP request headers directly,
# always available on every render with no async round-trip).
_COOKIE_NAME = "sb_session"
_COOKIE_TTL_DAYS = 30

def _save_session_cookie(session):
    """Queue a JS cookie write for the next render."""
    try:
        payload = json.dumps({
            "access_token":  session.access_token,
            "refresh_token": session.refresh_token,
        })
        st.session_state["_cookie_pending"] = payload
    except Exception:
        pass

def _clear_session_cookie():
    st.session_state["_cookie_pending"] = "__clear__"

# Flush any pending cookie writes via JavaScript before anything else runs.
# JS writes the cookie in the browser; st.context.cookies reads it on the
# next page load from the HTTP request headers.
_pending = st.session_state.pop("_cookie_pending", None)
if _pending == "__clear__":
    st_components.html(
        f"<script>window.parent.document.cookie='{_COOKIE_NAME}=;max-age=0;path=/';</script>",
        height=0,
    )
elif _pending:
    _encoded = quote(_pending)
    _ttl = _COOKIE_TTL_DAYS * 86400
    st_components.html(
        f"<script>window.parent.document.cookie='{_COOKIE_NAME}={_encoded};max-age={_ttl};path=/;SameSite=Lax';</script>",
        height=0,
    )

# Restore session from cookie on page refresh.
if "user" not in st.session_state and not DEV_MODE:
    try:
        raw = st.context.cookies.get(_COOKIE_NAME)
    except Exception:
        raw = None

    if raw:
        try:
            tokens = json.loads(unquote(raw))
            restored = storage.supabase.auth.set_session(
                tokens["access_token"], tokens["refresh_token"]
            )
            if restored and restored.user:
                st.session_state["session"] = restored.session
                st.session_state["user"]    = restored.user
                st.session_state["user_id"] = restored.user.id
        except Exception:
            _clear_session_cookie()

# If Supabase returns tokens in the URL hash (implicit flow), this JS snippet
# reads them and re-navigates to the same URL with tokens as query params so
# Streamlit's Python side can see them.
st_components.html("""
<script>
(function() {
    const win = window.parent || window;
    const hash = win.location.hash.substring(1);
    if (!hash) return;
    const p = new URLSearchParams(hash);
    const at = p.get('access_token');
    const rt = p.get('refresh_token');
    if (at && rt) {
        const url = new URL(win.location.href);
        url.hash = '';
        url.searchParams.set('access_token', at);
        url.searchParams.set('refresh_token', rt);
        win.location.replace(url.toString());
    }
})();
</script>
""", height=0)

query_params = st.query_params

# Implicit-flow callback: tokens arrive as query params (set by the JS above)
if "access_token" in query_params and "user" not in st.session_state:
    try:
        restored = storage.supabase.auth.set_session(
            query_params["access_token"], query_params["refresh_token"]
        )
        if restored and restored.user:
            st.session_state["session"] = restored.session
            st.session_state["user"]    = restored.user
            st.session_state["user_id"] = restored.user.id
            _save_session_cookie(restored.session)
            st.query_params.clear()
            st.rerun()
    except Exception as e:
        st.error(f"Login failed: {e}")

# 🛑 GATE 1: LOGIN CHECK
if "user" not in st.session_state:
    render_login(storage.supabase, on_login=_save_session_cookie)
    st.stop()

# 👤 USER CONTEXT
user = st.session_state["user"]
user_id = user.id

# SIDEBAR: LOGOUT & INFO
with st.sidebar:
    st.markdown("""
    <div style="padding: 1.25rem 0 0.75rem; font-family: 'DM Sans', sans-serif;
                font-size: 0.62rem; letter-spacing: 0.22em; text-transform: uppercase;
                color: #C9A96E;">
        ✦ &nbsp; AI Personal Stylist
    </div>
    """, unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:0.78rem; color:#6A6560; padding-bottom:0.5rem;'>{user.email}</div>", unsafe_allow_html=True)
    col_settings, col_logout = st.columns(2)
    with col_settings:
        if st.button("Settings", key="open_settings"):
            render_settings(storage, user_id)
    with col_logout:
        if st.button("Log Out", key="sidebar_logout"):
            storage.supabase.auth.sign_out()
            _clear_session_cookie()
            st.session_state.clear()
            st.rerun()
    st.markdown("---")

# 🛑 GATE 2: PROFILE CHECK
if "profile_complete" not in st.session_state:
    existing_profile = storage.get_profile(user_id)
    if existing_profile:
        st.session_state["profile_complete"] = True
        st.session_state["user_profile"] = existing_profile
        st.rerun()
    else:
        st.session_state["profile_complete"] = False

if not st.session_state["profile_complete"]:
    render_onboarding(storage, user_id)
    st.stop()

# ✅ READY: Load User Profile
user_profile = st.session_state["user_profile"]

# 🎨 FIRST-TIME BOARD BUILD: trigger automatically if user has no inspiration items yet
if not st.session_state.get("_inspo_first_run_checked"):
    st.session_state["_inspo_first_run_checked"] = True
    if not inspo_store.fetch_top_items(user_id=user_id, limit=1):
        st.session_state["_inspo_building"] = True

# =========================================================
# 2. APP INITIALIZATION
# =========================================================

# A. LOAD STATIC RULES (One-time load)
@st.cache_resource
def get_style_rules():
    # We use storage.load_config for static rules files
    return storage.load_config("style_rules.json")

style_rules = get_style_rules()

# B. INITIALIZE CLIENTS & STATE
if "messages" not in st.session_state:
    st.session_state.messages = []

if "outfit_ratings" not in st.session_state:
    st.session_state.outfit_ratings = {}  # outfit_id -> {"rating": int|None, "saved": bool, "db_id": str}

if "catalog" not in st.session_state:
    st.session_state.catalog = CatalogClient()

if "manager" not in st.session_state:
    client = OpenAIClient()
    # Initialize Manager with REAL user data
    st.session_state.manager = ConversationManager(
        client=client, 
        user_profile=user_profile,
        style_rules=style_rules,
        storage = storage,
        dev_mode = DEV_MODE
    )
    st.session_state.manager.ux_callback = ux_callback
    
    # Send a personalized Welcome Message
    first_name = user_profile.get('full_name', 'Fashionista').split()[0]

# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

def _star_str(rating: int) -> str:
    return "★" * rating + "☆" * (5 - rating)

def _render_rating_badge(rating_data: dict):
    """Shows a static rating line under a previously-rated outfit."""
    parts = []
    r = rating_data.get("rating")
    s = rating_data.get("saved")
    if r:
        parts.append(f"{_star_str(r)} {r}/5")
    if s:
        parts.append("♡ Saved")
    if parts:
        st.markdown(
            f"<div style='margin-top:6px; font-size:0.8rem; color:#C9A96E; letter-spacing:0.04em;'>"
            f"{'  ·  '.join(parts)}</div>",
            unsafe_allow_html=True,
        )

def _render_rating_widget(outfit_id: str, db_id: str):
    """Shows the star-rating + save widget for an unrated outfit."""
    st.markdown(
        "<div style='margin:1rem 0 0.4rem; font-size:0.7rem; letter-spacing:0.14em; "
        "text-transform:uppercase; color:#9C9590;'>Rate this look</div>",
        unsafe_allow_html=True,
    )
    col_stars, col_save = st.columns([4, 1])
    with col_stars:
        try:
            fb_val = st.feedback("stars", key=f"fb_{outfit_id}")
        except AttributeError:
            # Fallback for older Streamlit versions
            chosen = st.radio(
                "Stars",
                options=["★", "★★", "★★★", "★★★★", "★★★★★"],
                horizontal=True,
                label_visibility="collapsed",
                key=f"fb_{outfit_id}",
            )
            fb_val = ["★", "★★", "★★★", "★★★★", "★★★★★"].index(chosen) if chosen else None
    with col_save:
        save_clicked = st.button("♡ Save", key=f"save_{outfit_id}", use_container_width=True)

    # Persist rating on any interaction
    if save_clicked or (fb_val is not None and outfit_id not in st.session_state.outfit_ratings):
        r_val = (fb_val + 1) if fb_val is not None else None
        st.session_state.outfit_ratings[outfit_id] = {
            "rating": r_val,
            "saved": save_clicked,
            "db_id": db_id,
        }
        if db_id:
            storage.save_outfit_rating(user_id, db_id, r_val or 3, save_clicked)
        if save_clicked:
            st.toast("Saved to your style history ♡")
        elif r_val:
            st.toast(f"Rated {_star_str(r_val)}")
        st.rerun()

def display_outfit_recommendation(response_data):
    """Renders the visual moodboard."""
    # 1. The Reasoning (NEW)
    with st.container():
        st.subheader("💡 The Edit")

        reasoning = (response_data.get("reasoning") or "").strip()
        outfit0 = (response_data.get("outfit_options") or [{}])[0]
        items0 = outfit0.get("items") or []

        # Make a compact list like: “Hero: ___ • Key changes: ___ • Palette: ___”
        hero_guess = ""
        if items0:
            # lightweight heuristic: treat Outerwear or Accessory as hero if present, else Shoes, else Top
            priority = ["Outerwear", "Accessory", "Shoes", "Top", "Bottom", "OnePiece"]
            by_cat = {it.get("category"): it for it in items0 if isinstance(it, dict)}
            for cat in priority:
                if cat in by_cat:
                    hero_guess = by_cat[cat].get("item_name") or ""
                    break

        with st.container(border=True):
            st.markdown(
            f"**Editor's note**\n\n"
            f"- **Hero:** {hero_guess or 'Clean silhouette'}\n"
            f"- **Strategy:** {reasoning or 'Balanced proportions + season-friendly palette.'}"
        )
    
    # 2. The Visuals
    outfit_options = response_data.get('outfit_options', [])
    if not outfit_options: return

    # We take the first option for now (simplify for MVP)
    outfit_items = outfit_options[0]['items']
    visuals_map = st.session_state.catalog.search_products_parallel(outfit_items)

    st.divider()
    cols = st.columns(len(outfit_items))
    
    for idx, item in enumerate(outfit_items):
        with cols[idx]:
            # Handle object/dict differences
            i_name = item.get('item_name') if isinstance(item, dict) else item.item_name
            i_cat = item.get('category') if isinstance(item, dict) else item.category

            # Visual Indicator for "Owned" items
            is_owned = item.get("owned") if isinstance(item, dict) else getattr(item, "owned", False)
            if is_owned:
                st.markdown(f"**{i_cat}** <span style='background-color:#d4edda; color:#155724; padding:2px 6px; border-radius:4px; font-size:12px;'>CLOSET</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"**{i_cat}**")

            # Render Image
            product = visuals_map.get(i_name)
            if product and product.get('image'):
                st.image(product['image'], width='stretch')
                st.caption(f"[{product.get('title', 'View Item')[:30]}...]({product.get('link', '#')})")
            else:
                # Fallback text if no image found
                st.warning("No image found")
                st.caption(i_name)
            
            # WHY — always show full text
            item_dict = item if isinstance(item, dict) else item.model_dump()

            reason = (item_dict.get("reason") or "").strip()

            # remove [OWNED] prefix for display
            if item_dict.get("owned") and reason.startswith("[OWNED]"):
                reason = reason.replace("[OWNED]", "").strip()

            if reason:
                st.markdown(
                    f"""
                    <div style="
                        margin-top: 6px;
                        font-size: 0.85rem;
                        line-height: 1.4;
                        color: #6b7280;
                    ">
                    {reason}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown("<hr style='margin:8px 0; opacity:0.2;'>", unsafe_allow_html=True)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_image_bytes(url: str) -> bytes:
    """
    Fetch image bytes. Returns None if broken / not an image / blocked.
    Cached so reruns don't refetch.
    """
    if not url.startswith(("http://", "https://")):
        return None
    try:
        r = requests.get(
            url,
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        if r.status_code != 200:
            return None

        ctype = (r.headers.get("Content-Type") or "").lower()
        if "image" not in ctype:
            return None

        if not r.content or len(r.content) < 5000:  # tiny responses are often error placeholders
            return None

        return r.content
    except Exception:
        return None

def normalize_image_url(url: str) -> str:
    """Reduce near-duplicate URLs by stripping query + fragment."""
    u = (url or "").strip()
    if not u:
        return u
    parts = urlsplit(u)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

def _needs_proxy(url: str) -> bool:
    """Instagram CDN URLs are referrer-locked and won't load in an iframe — proxy them."""
    return "cdninstagram.com" in url or "fbcdn.net" in url


def _diversity_rank(items: list, window: int = 30) -> list:
    """
    Round-robin by source_name so no single source dominates the top of the board.
    Within each source, items are already sorted by score (highest first).
    We interleave them: take the best item from each source in rotation.
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for it in items:
        buckets[it.get("source_name") or ""].append(it)
    # Each bucket is already score-sorted from the DB query
    ranked = []
    while any(buckets.values()):
        for key in list(buckets.keys()):
            if buckets[key]:
                ranked.append(buckets[key].pop(0))
            else:
                del buckets[key]
        if len(ranked) >= window * 10:  # safety cap
            break
    return ranked


def _build_inspo_items(user_id: str, inspo_store) -> list:
    """
    Fetch, diversity-rank, and deduplicate inspiration items.
    Instagram CDN URLs are proxied server-side (fetched as bytes, sent as base64).
    All other URLs are passed directly to the browser.
    """
    from concurrent.futures import ThreadPoolExecutor

    # Fetch a large pool, diversity-rank, then serve the top 60
    raw = inspo_store.fetch_top_items(user_id=user_id, limit=400) or []
    raw = _diversity_rank(raw)[:60]

    seen_urls: set = set()
    deduped = []
    for it in raw:
        url = normalize_image_url(it.get("image_url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(it)

    # Proxy Instagram URLs in parallel; leave others as-is
    proxy_items = [(i, it) for i, it in enumerate(deduped) if _needs_proxy(it.get("image_url", ""))]

    if proxy_items:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(fetch_image_bytes, it.get("image_url", "")): i for i, it in proxy_items}
            for future, idx in futures.items():
                img_bytes = future.result()
                if img_bytes:
                    deduped[idx] = {**deduped[idx], "image_bytes": img_bytes}
                else:
                    deduped[idx] = None  # mark broken

    result = []
    for it in deduped:
        if it is None:
            continue
        # Persist saved state so hearts stay filled after page reload
        it = {**it, "saved": it.get("feedback") == "save"}
        result.append(it)
    return result


# =========================================================
# 4. MAIN INTERFACE
# =========================================================
@st.cache_data(ttl=900)
def get_current_temperature_c(location_text: str):
    if not location_text:
        return None
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={quote(location_text)}&count=1"
        with urlopen(geo_url, timeout=3) as response:
            geo_data = json.load(response)
        results = geo_data.get("results") or []
        if not results:
            return None
        latitude = results[0].get("latitude")
        longitude = results[0].get("longitude")
        if latitude is None or longitude is None:
            return None

        weather_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}&current=temperature_2m"
        )
        with urlopen(weather_url, timeout=3) as response:
            weather_data = json.load(response)
        temperature = (weather_data.get("current") or {}).get("temperature_2m")
        if temperature is None:
            return None
        return round(float(temperature))
    except Exception:
        return None

location_city = user_profile.get("location_city", "Unknown")
season = st.session_state.manager._infer_season()
temperature_c = get_current_temperature_c(location_city)
weather_label = f"{temperature_c}°C" if temperature_c is not None else "Weather n/a"
now_label = datetime.now().strftime("%b %d, %Y • %I:%M %p")
_first = user_profile.get('full_name', 'You').split()[0]
st.markdown(f"""
<div class="stylist-header">
    <div class="header-eyebrow">{location_city} &nbsp;·&nbsp; {season} &nbsp;·&nbsp; {weather_label}</div>
    <div class="header-title">Dressed for {_first}</div>
    <div class="header-meta">{now_label}</div>
</div>
""", unsafe_allow_html=True)

# Persist active tab across reruns using localStorage
st_components.html("""
<script>
(function () {
  var KEY = 'st_active_tab';
  function restoreTab() {
    var saved = parseInt(localStorage.getItem(KEY) || '0', 10);
    if (saved === 0) return;
    var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
    if (tabs[saved]) tabs[saved].click();
  }
  function watchTabs() {
    var list = window.parent.document.querySelector('[data-baseweb="tab-list"]');
    if (!list) { setTimeout(watchTabs, 150); return; }
    list.addEventListener('click', function (e) {
      var tab = e.target.closest('[data-baseweb="tab"]');
      if (!tab) return;
      var idx = Array.from(list.querySelectorAll('[data-baseweb="tab"]')).indexOf(tab);
      localStorage.setItem(KEY, String(idx));
    });
    restoreTab();
  }
  setTimeout(watchTabs, 120);
}());
</script>
""", height=0)

# If the inspiration pipeline is running, show a full-page spinner and stop.
# This must happen BEFORE tabs are rendered so the old tab content never shows.
if st.session_state.get("_inspo_building"):
    st.session_state.pop("_inspo_items", None)
    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
    with st.spinner("Building your inspiration board… this takes about a minute."):
        try:
            from agents.inspiration_agent import run as run_inspiration
            run_inspiration(user_id=user_id, user_profile=user_profile)
            fetch_image_bytes.clear()
        except Exception as e:
            st.error(f"Pipeline failed: {e}")
    del st.session_state["_inspo_building"]
    st.session_state.pop("_inspo_items", None)
    st.rerun()

tab_stylist, tab_liked, tab_inspo = st.tabs(["Stylist", "Liked Outfits", "Inspiration Board"])

with tab_stylist:
    # A. RENDER CHAT HISTORY
    # Rating widget is rendered inline after each outfit so user follow-ups always
    # appear below it, not sandwiched between the outfit and the rating.
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if isinstance(msg["content"], dict):
                display_outfit_recommendation(msg["content"])
                oid = msg.get("outfit_id", "")
                if oid and oid in st.session_state.outfit_ratings:
                    _render_rating_badge(st.session_state.outfit_ratings[oid])
            else:
                st.markdown(msg["content"])

        if msg.get("type") == "outfit":
            oid = msg.get("outfit_id", "")
            dbid = msg.get("db_id", "")
            if oid and oid not in st.session_state.outfit_ratings:
                _render_rating_widget(oid, dbid)

    # C. CHAT INPUT — always native, always sticky at bottom like Claude/ChatGPT
    has_user_messages = any(m["role"] == "user" for m in st.session_state.messages)
    if not has_user_messages:
        _first_name = user_profile.get("full_name", "").split()[0]
        _color = user_profile.get("color_season", "")
        _body = user_profile.get("body_style_essence", "")
        _profile = ", ".join(filter(bool, [_color, _body]))
        st.markdown(
            f"<div style='text-align:center; padding:3rem 0 1.5rem;'>"
            f"<p style='font-family:Playfair Display,serif; font-size:1.15rem; font-style:italic; color:#9C9590;'>"
            f"Hi <strong>{_first_name}</strong>!"
            + (f" I see you're a <strong>{_profile}</strong>." if _profile else "")
            + " What are you dressing for today?</p></div>",
            unsafe_allow_html=True,
        )

    prompt = st.chat_input("e.g. I need a brunch outfit for Saturday…")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt, "type": "text"})
        st.session_state["_pending_prompt"] = prompt
        st.rerun()

    if "_pending_prompt" in st.session_state:
        prompt = st.session_state.pop("_pending_prompt")

        # Assistant Response
        with st.chat_message("assistant"):
            status_placeholder = st.empty()
            st.session_state.ux_events = []
            _cs_counter = [0]   # mutable so the closure can increment it

            def ux_callback_live(event):
                st.session_state.ux_events.append(event)
                msg = event.get("message") or "Working…"
                label = msg.lstrip("🧠👂🛍️✨✅❌ ").strip()
                _cs_counter[0] += 1
                with status_placeholder:
                    chat_status(label=label, visible=True, key=f"cs_{_cs_counter[0]}")

            st.session_state.manager.ux_callback = ux_callback_live

            try:
                if not st.session_state.manager.current_outfit:
                    ux_callback_live({"message": "🧠 Understanding your request…"})
                    response_payload = st.session_state.manager.start_new_session(
                        user_request_context={},
                        user_query=prompt,
                        status_callback=None,
                    )
                else:
                    ux_callback_live({"message": "👂 Listening to your feedback…"})
                    response_payload = st.session_state.manager.refine_session(prompt)

                status_placeholder.empty()

                if isinstance(response_payload, dict):
                    display_outfit_recommendation(response_payload)
                    _outfit_id = response_payload.get("id", "")
                    _db_id = st.session_state.manager.conversation_state.get("last_revision_db_id") or ""
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response_payload,
                        "type": "outfit",
                        "outfit_id": _outfit_id,
                        "db_id": _db_id,
                    })
                    # Show rating widget immediately after new outfit
                    if _outfit_id and _outfit_id not in st.session_state.outfit_ratings:
                        _render_rating_widget(_outfit_id, _db_id)
                else:
                    st.markdown(response_payload)
                    st.session_state.messages.append({"role": "assistant", "content": response_payload, "type": "text"})

            except Exception as e:
                status_placeholder.empty()
                st.error(f"Something went wrong: {e}")
                st.code(traceback.format_exc())

with tab_liked:
    liked_rows = storage.fetch_liked_outfits(user_id, limit=20)
    if not liked_rows:
        st.markdown(
            "<div style='text-align:center; padding: 3rem 0 1rem;'>"
            "<p style='font-family:Playfair Display,serif; font-size:1.3rem; color:#1C1C1E;'>Nothing saved yet</p>"
            "<p style='font-size:0.85rem; color:#9C9590; margin-bottom:1.5rem;'>"
            "Rate an outfit 4 or 5 stars — or hit Save — and it'll live here.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<p style='font-size:0.8rem; color:#9C9590; margin-bottom:1rem;'>"
            f"{len(liked_rows)} look{'s' if len(liked_rows) != 1 else ''} saved</p>",
            unsafe_allow_html=True,
        )
        for row in liked_rows:
            final_outfit = row.get("final_outfit") or {}
            occasion = final_outfit.get("occasion") or row.get("user_query") or "Outfit"
            season_label = final_outfit.get("season") or ""
            created_raw = row.get("created_at") or ""
            created = created_raw[:10] if created_raw else ""
            user_rating = row.get("user_rating")
            user_saved = row.get("user_saved", False)
            editor_score = row.get("final_score")
            reasoning = (final_outfit.get("reasoning") or "").strip()

            with st.container(border=True):
                col_meta, col_rating = st.columns([5, 2])
                with col_meta:
                    st.markdown(
                        f"<div style='font-family:Playfair Display,serif; font-size:1.05rem; "
                        f"color:#1C1C1E; margin-bottom:2px;'>{occasion}</div>",
                        unsafe_allow_html=True,
                    )
                    meta_parts = []
                    if created:
                        meta_parts.append(created)
                    if season_label:
                        meta_parts.append(season_label)
                    if editor_score:
                        meta_parts.append(f"Editor {editor_score}/10")
                    if meta_parts:
                        st.caption("  ·  ".join(meta_parts))
                with col_rating:
                    badge_parts = []
                    if user_rating:
                        badge_parts.append(_star_str(user_rating))
                    if user_saved:
                        badge_parts.append("♡")
                    if badge_parts:
                        st.markdown(
                            f"<div style='color:#C9A96E; font-size:1.15rem; text-align:right; "
                            f"padding-top:4px;'>{'  '.join(badge_parts)}</div>",
                            unsafe_allow_html=True,
                        )

                # Reasoning snippet
                if reasoning:
                    st.markdown(
                        f"<div style='margin-top:0.2rem; margin-bottom:0.75rem; font-size:0.82rem; "
                        f"color:#6b7280; font-style:italic; line-height:1.45;'>"
                        f"{reasoning[:220]}{'…' if len(reasoning) > 220 else ''}</div>",
                        unsafe_allow_html=True,
                    )

                # Image grid — same as stylist tab; disk-cached so no extra API calls
                opts = final_outfit.get("outfit_options") or []
                items = (opts[0].get("items") or []) if opts and isinstance(opts[0], dict) else []
                if items:
                    visuals_map = st.session_state.catalog.search_products_parallel(items)
                    img_cols = st.columns(len(items))
                    for idx, it in enumerate(items):
                        with img_cols[idx]:
                            i_name = it.get("item_name") or ""
                            i_cat = it.get("category") or ""
                            is_owned = it.get("owned", False)
                            if is_owned:
                                st.markdown(
                                    f"**{i_cat}** <span style='background:#d4edda;color:#155724;"
                                    f"padding:2px 6px;border-radius:4px;font-size:12px;'>CLOSET</span>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(f"**{i_cat}**")
                            product = visuals_map.get(i_name)
                            if product and product.get("image"):
                                st.image(product["image"], width="stretch")
                                st.caption(
                                    f"[{product.get('title', 'View Item')[:30]}…]"
                                    f"({product.get('link', '#')})"
                                )
                            else:
                                st.caption(i_name)

with tab_inspo:
    if "_inspo_items" not in st.session_state:
        st.session_state["_inspo_items"] = _build_inspo_items(user_id, inspo_store)
    items = st.session_state["_inspo_items"]

    if not items:
        st.markdown(
            "<div style='text-align:center; padding: 3rem 0 1rem;'>"
            "<p style='font-family:Playfair Display,serif; font-size:1.3rem; color:#1C1C1E;'>Your board is empty</p>"
            "<p style='font-size:0.85rem; color:#9C9590; margin-bottom:1.5rem;'>We'll search for outfit photos of your style icons, brands, and motifs.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        col = st.columns([1, 2, 1])[1]
        with col:
            if st.button("Build my inspiration board", use_container_width=True):
                st.session_state["_inspo_building"] = True
                st.rerun()
    else:
        event = inspo_board_component(items=items, key="inspo_board")
        if event and isinstance(event, dict):
            action = event.get("action")
            item_id = event.get("id")
            last = st.session_state.get("_last_inspo_event")
            if event != last:
                st.session_state["_last_inspo_event"] = event
                if action == "refresh":
                    # Full agent re-run — pulls fresh images, not just a cache clear
                    st.session_state["_inspo_building"] = True
                    st.session_state.pop("_inspo_items", None)
                    st.rerun()
                elif action == "save" and item_id:
                    inspo_store.save_item(user_id, item_id)
                    # Update in-place so heart stays filled without a full reload
                    saved_item = None
                    for it in st.session_state.get("_inspo_items", []):
                        if it.get("id") == item_id:
                            it["saved"] = True
                            saved_item = it
                            break
                    st.toast("Saved to your style DNA ✦")
                    # Track save counts per source — trigger mini-expansion at 3
                    save_counts = st.session_state.setdefault("_inspo_save_counts", {})
                    if saved_item:
                        src = saved_item.get("source_name") or ""
                        save_counts[src] = save_counts.get(src, 0) + 1
                        if save_counts[src] == 3:
                            # Fire mini-expansion in background thread
                            import threading
                            from agents.inspiration_agent import mini_expand
                            threading.Thread(
                                target=mini_expand,
                                kwargs=dict(
                                    user_id=user_id,
                                    source_name=src,
                                    source_type=saved_item.get("source_type") or "icon",
                                    tags=saved_item.get("tags") or [],
                                    storage=storage,
                                    inspiration_store=inspo_store,
                                ),
                                daemon=True,
                            ).start()
                            st.toast(f"Finding more from {src}… ✦")
                elif action == "hide" and item_id:
                    # Delete permanently — item will never resurface
                    inspo_store.delete_item(user_id, item_id)
                    # Remove from session cache so it doesn't reappear on rerun
                    st.session_state["_inspo_items"] = [
                        it for it in st.session_state.get("_inspo_items", [])
                        if it.get("id") != item_id
                    ]

