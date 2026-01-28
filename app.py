import json
import streamlit as st
import traceback
from datetime import datetime
from urllib.parse import quote
from urllib.request import urlopen
from dotenv import load_dotenv

# --- SERVICES & AGENTS ---
from services.storage import StorageService
from services.catalog import CatalogClient
from core.client import OpenAIClient
from workflow.manager import ConversationManager

# --- VIEWS ---
from views.login import render_login
from views.onboarding import render_onboarding

# --- CONFIG ---
load_dotenv()
st.set_page_config(page_title="AI Personal Stylist", page_icon="✨", layout="wide")

if "storage" not in st.session_state:
    st.session_state["storage"] = StorageService()

storage = st.session_state["storage"]

# ==========================================
# 🛠️ DEV MODE: BYPASS LOGIN
# ==========================================
# Set this to True to skip login. Set to False for production.
DEV_MODE = True 

if DEV_MODE and "user" not in st.session_state:
    print("⚠️ DEV MODE ACTIVE: Using Mock User")
    
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
    st.markdown(f"**Logged in as:**\n{user.email}")
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
    # 1. The Reasoning
    with st.container():
        st.subheader("💡 The Edit")
        st.info(response_data.get('reasoning', "Here is a look curated just for you."))
    
    # 2. The Visuals
    outfit_options = response_data.get('outfit_options', [])
    if not outfit_options: return

    # We take the first option for now (simplify for MVP)
    outfit_items = outfit_options[0]['items']
    prog = st.progress(0, text="🛍️ Finding matching items…")
    visuals_map = {}

    try:
        progress = st.progress(90, text="🛍️ Finding matching items…")
        visuals_map = st.session_state.catalog.search_products_parallel(outfit_items)
        progress.progress(100, text="✨ Done!")

    finally:
        # Optional: keep it for a moment or remove it
        prog.empty()

    st.divider()
    cols = st.columns(len(outfit_items))
    
    for idx, item in enumerate(outfit_items):
        with cols[idx]:
            # Handle object/dict differences
            i_name = item.get('item_name') if isinstance(item, dict) else item.item_name
            i_cat = item.get('category') if isinstance(item, dict) else item.category
            i_reason = item.get('reason') if isinstance(item, dict) else getattr(item, 'reason', "")

            # Visual Indicator for "Owned" items
            is_owned = item.get("owned") if isinstance(item, dict) else getattr(item, "owned", False)
            if is_owned:
                st.markdown(f"**{i_cat}** <span style='background-color:#d4edda; color:#155724; padding:2px 6px; border-radius:4px; font-size:12px;'>CLOSET</span>", unsafe_allow_html=True)
                clean_reason = i_reason.replace("[OWNED]", "").strip()
            else:
                st.markdown(f"**{i_cat}**")
                clean_reason = i_reason

            # Render Image
            product = visuals_map.get(i_name)
            if product and product.get('image'):
                st.image(product['image'], use_container_width=True)
                st.caption(f"[{product.get('title', 'View Item')[:30]}...]({product.get('link', '#')})")
            else:
                # Fallback text if no image found
                st.warning("No image found")
                st.caption(i_name)
            
            # Why this item?
            if clean_reason:
                with st.expander("Why?"):
                    st.write(clean_reason)

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
st.caption(f"{location_city} • {season} • {weather_label} • {now_label}")

st.title(f"✨ Stylist for {user_profile.get('full_name')}")

# A. RENDER CHAT HISTORY
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if isinstance(msg["content"], dict): 
            display_outfit_recommendation(msg["content"])
        else:
            st.markdown(msg["content"])

# B. CHAT INPUT HANDLER
if prompt := st.chat_input("Ex: I need a brunch outfit for Saturday..."):
    # 1. User Message
    st.session_state.messages.append({"role": "user", "content": prompt, "type": "text"})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Assistant Response
    with st.chat_message("assistant"):
        status_line = st.empty()
        progress = st.progress(0, text="🧠 Starting…")

        st.session_state.ux_events = []

        PHASE_TO_PROGRESS = {
            "intent": 8,
            "interpret": 15,
            "generate": 45,
            "editor": 70,
            "search": 90,
            "done": 100,
            "info": 5,
        }

        def ux_callback_live(event):
            st.session_state.ux_events.append(event)

            msg = event.get("message") or "Working…"
            phase = event.get("phase") or "info"
            pct = PHASE_TO_PROGRESS.get(phase, 10)

            status_line.markdown(msg)
            progress.progress(pct, text=msg)

        # IMPORTANT: manager uses this for UX events
        st.session_state.manager.ux_callback = ux_callback_live

        try:
            # NEW vs REFINE
            if not st.session_state.manager.current_outfit:
                ux_callback_live({"message": "🧠 Understanding your request…", "phase": "interpret"})
                response_payload = st.session_state.manager.start_new_session(
                    user_request_context={},
                    user_query=prompt,
                    status_callback=None,   # ✅ stop using status_callback; rely on manager._ux
                )
            else:
                ux_callback_live({"message": "👂 Listening to your feedback…", "phase": "intent"})
                response_payload = st.session_state.manager.refine_session(prompt)

            # Render
            if isinstance(response_payload, dict):
                # If display_outfit_recommendation does product search internally,
                # this will show right before that blocking call.
                ux_callback_live({"message": "🛍️ Finding matching items…", "phase": "search"})

                display_outfit_recommendation(response_payload)

                st.session_state.messages.append({"role": "assistant", "content": response_payload, "type": "outfit"})
                ux_callback_live({"message": "✨ Outfit ready!", "phase": "done"})
            else:
                st.markdown(response_payload)
                st.session_state.messages.append({"role": "assistant", "content": response_payload, "type": "text"})
                ux_callback_live({"message": "✅ Done", "phase": "done"})

        except Exception as e:
            status_line.markdown("❌ Error")
            progress.progress(100, text="❌ Error")
            st.error(f"Something went wrong: {e}")
            st.code(traceback.format_exc())

# =========================================================
# 5. DEV TOOLS (Hidden in Expander)
# =========================================================
with st.sidebar:
    with st.expander("🕵️ Debug Info"):
        if st.session_state.manager:
            st.write("User Context:", st.session_state.manager.user_profile)
            st.write("Current Rules:", style_rules.keys())
