import json
import streamlit as st
import requests
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote, urlsplit, urlunsplit
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

# --- COMPONENTS ---
from components.inspiration_board import inspiration_board as inspo_board_component
from components.chat_status import chat_status
from components.chat_input import chat_input_custom
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

/* Chat input */
[data-testid="stChatInput"] > div {
    border: 1px solid #DDD6CE !important;
    border-radius: 12px !important;
    background: #FFFFFF !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
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
DEV_MODE = True 

if DEV_MODE and "user" not in st.session_state:
    # 1. Mock the User Object (What Supabase usually gives you)
    class MockUser:
        def __init__(self):
            self.id = "dev-user-123"
            self.email = "isabel@dev.com"
    
    # 2. Mock the Session Object (So code asking for tokens doesn't crash)
    class MockSession:
        def __init__(self):
            self.access_token = "fake-dev-token"
            self.user = MockUser()

    # 3. Inject into Streamlit State
    st.session_state["user"] = MockUser()
    st.session_state["user_id"] = "dev-user-123"
    st.session_state["session"] = MockSession()
    
    # 4. Mock the Database Profile
    st.session_state["user_profile"] = {
        "id": "dev-user-123",
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
    st.session_state["profile_complete"] = True

# =========================================================
# 1. AUTHENTICATION & SESSION MANAGEMENT
# =========================================================
if "ux_events" not in st.session_state:
    st.session_state.ux_events = []

def ux_callback(event):
    st.session_state.ux_events.append(event)

query_params = st.query_params 

if "code" in query_params:
    try:
        # Now 'storage' remembers the flow!
        session = storage.supabase.auth.exchange_code_for_session({
            "auth_code": query_params["code"]
        })
        
        # Save User
        st.session_state["session"] = session
        st.session_state["user"] = session.user
        st.session_state["user_id"] = session.user.id
        
        # Cleanup URL and Reload
        st.query_params.clear()
        st.rerun()
        
    except Exception as e:
        st.error(f"Login failed: {e}")
        # Optional: Print detail for debugging
        # st.write(e)

# 🛑 GATE 1: LOGIN CHECK
if "user" not in st.session_state:
    render_login(storage.supabase)
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
    if st.button("Log Out"):
        storage.supabase.auth.sign_out()
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
    welcome_msg = f"Hi {first_name}! I see you're a **{user_profile.get('color_season')}, {user_profile.get('body_style_essence')}**. How can I help you dress today?"
    st.session_state.messages.append({"role": "assistant", "content": welcome_msg, "type": "text"})

# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

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
                st.image(product['image'], use_container_width=True)
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

def _build_inspo_items(user_id: str, inspo_store) -> list:
    """Fetch, deduplicate, and pre-fetch images for the inspiration board."""
    raw = inspo_store.fetch_top_items(user_id=user_id, limit=100) or []

    # Deduplicate by normalised URL
    seen_urls: set = set()
    candidates = []
    for it in raw:
        url = normalize_image_url(it.get("image_url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append((it, url))

    MAX_SHOW = 24
    MAX_CHECK = 80
    batch = candidates[:MAX_CHECK]

    # Parallel fetch — same pattern as CatalogClient.search_products_parallel
    with ThreadPoolExecutor(max_workers=8) as ex:
        bytes_list = list(ex.map(lambda p: fetch_image_bytes(p[1]), batch))

    good = []
    seen_hashes: set = set()
    for (it, url), img_bytes in zip(batch, bytes_list):
        if not img_bytes:
            continue
        h = hash(img_bytes)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        good.append({**it, "image_bytes": img_bytes})
        if len(good) >= MAX_SHOW:
            break

    return good


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

tab_stylist, tab_inspo = st.tabs(["Stylist", "Inspiration Board"])

with tab_stylist:
    # A. RENDER CHAT HISTORY
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if isinstance(msg["content"], dict):
                display_outfit_recommendation(msg["content"])
            else:
                st.markdown(msg["content"])
    # B. CUSTOM CHAT INPUT
    raw_input = chat_input_custom(
        placeholder="Ex: I need a brunch outfit for Saturday…",
        key="chat_input_field",
    )
    # Deduplicate: component value persists in session state until a new one is sent
    prompt = None
    if raw_input and raw_input != st.session_state.get("_chat_processed"):
        st.session_state["_chat_processed"] = raw_input
        prompt = raw_input
    if prompt:
        # 1. User Message
        st.session_state.messages.append({"role": "user", "content": prompt, "type": "text"})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 2. Assistant Response
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
                    st.session_state.messages.append({"role": "assistant", "content": response_payload, "type": "outfit"})
                else:
                    st.markdown(response_payload)
                    st.session_state.messages.append({"role": "assistant", "content": response_payload, "type": "text"})

            except Exception as e:
                status_placeholder.empty()
                st.error(f"Something went wrong: {e}")
                st.code(traceback.format_exc())

with tab_inspo:
    items = _build_inspo_items(user_id, inspo_store)
    if not items:
        st.info("No inspiration items yet. Run your pipeline to populate the board.")
    else:
        event = inspo_board_component(items=items, key="inspo_board")
        if event and isinstance(event, dict):
            action = event.get("action")
            item_id = event.get("id")
            last = st.session_state.get("_last_inspo_event")
            if event != last:
                st.session_state["_last_inspo_event"] = event
                if action == "refresh":
                    fetch_image_bytes.clear()
                    st.rerun()
                elif action == "save" and item_id:
                    # No rerun — JS handles the ♡→♥ visual; rerunning destroys component state
                    inspo_store.log_feedback(user_id, item_id, "save")
                    st.toast("Saved to your style DNA ✦")
                elif action == "hide" and item_id:
                    # No rerun — JS removes the card with animation
                    inspo_store.log_feedback(user_id, item_id, "hide")

