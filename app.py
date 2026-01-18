import streamlit as st
from dotenv import load_dotenv

from agents.style_researcher import StyleResearcherAgent
from workflow.manager import ConversationManager
from core.client import OpenAIClient
from services.storage import DataLoader
from services.catalog import CatalogClient

load_dotenv()

# 1. PAGE CONFIGURATION
st.set_page_config(page_title="AI Personal Stylist", page_icon="🎨", layout="wide")

# 2. LOAD DATA & SERVICES
@st.cache_resource
def get_static_data():
    base_dir = '.'
    data = DataLoader(base_dir)
    return data

style_rules = get_static_data().style_rules

# --- HELPER: OUTFIT VISUALIZER ---
def display_outfit_recommendation(response_data):
    # 1. THE "PITCH" (The Overview)
    with st.container():
        st.subheader("💡 The Stylist's Edit")
        st.info(response_data.get('reasoning', "Here is a look curated just for you."))
    
    # 2. THE IMAGES (Visuals)
    outfit_options = response_data.get('outfit_options', [])
    if not outfit_options: return

    outfit_items = outfit_options[0]['items']
    
    with st.spinner("🛍️ Scanning stores for matches..."):
        visuals_map = st.session_state.catalog.search_products_parallel(outfit_items)

    st.divider()

    # 2. RENDER
    st.divider()
    cols = st.columns(len(outfit_items))
    
    for idx, item in enumerate(outfit_items):
        with cols[idx]:
            # 1. Normalize Access (Dict vs Object)
            if isinstance(item, dict):
                i_name = item.get('item_name')
                i_cat = item.get('category')
                i_reason = item.get('reason')
            else:
                i_name = item.item_name
                i_cat = item.category
                i_reason = getattr(item, 'reason', None)

            is_owned = "[OWNED]" in i_reason
            clean_reason = i_reason.replace("[OWNED]", "").strip()
            if is_owned:
                st.markdown(f"**{i_cat}** <span style='background-color:#d4edda; color:#155724; padding:2px 6px; border-radius:4px; font-size:12px;'>YOURS</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"**{i_cat}**")

            # 2. Get Visuals from Catalog
            product = visuals_map.get(i_name)
            
            # 3. Render Card
            if product and product.get('image'):
                st.image(product['image'], use_container_width=True)
                
                # We use the link from GOOGLE SHOPPING (product), not the LLM
                link_url = product.get('link', '#')
                title_text = product.get('title', 'View Item')[:30]
                
                st.caption(f"[{title_text}...]({link_url})")
                
                if product.get('price'):
                    st.caption(f"**{product.get('price')}**")
            else:
                st.info(f"🔎 {i_name}")
            
            st.markdown(f"**{i_cat}**")
            
            if i_reason:
                with st.expander("Why this?"):
                    st.write(i_reason)
            st.markdown(f"**{i_cat}**")

# 3. SIDEBAR: PROFILE SIMULATOR
with st.sidebar:
    st.sidebar.header("Developer Tools")
    dev_mode = st.sidebar.checkbox("⚡ Use Cached Initial Outfit", value=True)
    
    body_type_map = {
        "Straight": "straight_type",
        "Wave": "wave_type",
        "Natural": "natural_type"
    }

    color_season_map = {
        "Spring Warm": "spring_warm_tone",
        "Summer Cool": "summer_cool_tone",
        "Autumn Warm": "autumn_warm_tone",
        "Winter Cool": "winter_cool_tone"
    }

    st.header("👤 User Profile Simulator")
    selected_name = st.text_input("Name", value="Isabel")
    wear_pref = st.selectbox("Wear Preference", ["Womenswear", "Menswear", "Unisex"])
    body_type = body_type_map[st.selectbox("Body Essence", ["Straight", "Wave", "Natural"])]
    color_season = color_season_map[st.selectbox("Color Season", ["Spring Warm", "Summer Cool", "Autumn Warm", "Winter Cool"])]
    style_icon = st.text_input("Style Icon", value="Bae Suzy")
    
    cleaned_style_icon = StyleResearcherAgent(OpenAIClient())._sanitize_entity(style_icon)

    dynamic_profile = {
        "name": selected_name,
        "wear_preference": wear_pref,
        "body_style_essence": body_type,
        "personal_color": color_season,
        "style_references": [cleaned_style_icon] if cleaned_style_icon else []
    }

    if st.button("🔄 Reset / Apply Profile"):
        with st.chat_message("assistant"):
            with st.status("⚙️ Syncing Profile...", expanded=True) as status_box:
                def sidebar_updater(msg): st.write(msg)
                
                if st.session_state.manager is None:
                    client = OpenAIClient()
                    st.session_state.manager = ConversationManager(client=client, user_profile=dynamic_profile, style_rules=style_rules)

                summary_response = st.session_state.manager.update_profile_and_research(
                    new_profile_data=dynamic_profile,
                    status_callback=sidebar_updater
                )
                status_box.update(label="✅ Profile Synced!", state="complete", expanded=False)
        
        st.session_state.messages.append({"role": "assistant", "content": summary_response, "type": "text"})
        st.rerun()

# 4. INITIALIZE STATE
if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_started" not in st.session_state:
    st.session_state.session_started = False

if "manager" not in st.session_state or st.session_state.manager is None:
    client = OpenAIClient()
    data = get_static_data()
    catalog = CatalogClient()
    st.session_state.catalog = catalog
    st.session_state.manager = ConversationManager(
        client=client,
        user_profile=dynamic_profile,
        style_rules=style_rules,
        request_context_schema=data.request_context
    )
    
    welcome_msg = f"Hello {selected_name}! I see you're a **{color_season} {body_type}**. How can I help you dress today?"
    st.session_state.messages.append({"role": "assistant", "content": welcome_msg, "type": "text"})


# 5. MAIN CHAT INTERFACE
st.title("Your AI Stylist MVP")

# A. DISPLAY CHAT HISTORY
# We loop through history and decide HOW to render based on the 'type' or content
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        # Case 1: It's an Outfit Dictionary
        if isinstance(msg["content"], dict): 
            display_outfit_recommendation(msg["content"])
        # Case 2: It's just Text
        else:
            st.markdown(msg["content"])


# B. HANDLE USER INPUT
if prompt := st.chat_input("Ex: I have a holiday party and want to wear my black skirt..."):
    st.session_state.last_query = prompt

    # 1. Display User Message
    st.session_state.messages.append({"role": "user", "content": prompt, "type": "text"})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Generate AI Response
    with st.chat_message("assistant"):
        with st.status("🧠 Thinking... (Checking Rules & Researching)", expanded=True) as status_box:
            def ui_updater(message):
                st.write(message)

            try:
                response_payload = None
                
                if not st.session_state.session_started:
                    # START NEW SESSION
                    response_payload = st.session_state.manager.start_new_session(
                        user_request_context={}, 
                        user_query=prompt,
                        status_callback=ui_updater,
                        use_cache=dev_mode
                    )
                    st.session_state.session_started = True 
                else:
                    # REFINE SESSION
                    st.write("👂 Listening...")
                    response_payload = st.session_state.manager.refine_session(prompt)
                
                status_box.update(label="✨ Ready!", state="complete", expanded=False)
                
                # 3. RENDER & SAVE RESPONSE
                # Logic: Is it a Dict (Outfit) or String (Chat)?
                if isinstance(response_payload, dict):
                    display_outfit_recommendation(response_payload)
                    st.session_state.messages.append({"role": "assistant", "content": response_payload, "type": "outfit"})
                else:
                    st.markdown(response_payload)
                    st.session_state.messages.append({"role": "assistant", "content": response_payload, "type": "text"})
                
            except Exception as e:
                status_box.update(label="❌ Error", state="error")
                st.error(f"Something went wrong: {e}")
                import traceback
                st.write(traceback.format_exc())

# 6. DEBUG EXPANDER
with st.expander("🕵️‍♀️ Developer Debug View"):
    if st.session_state.manager:
        st.write("Current Context:", st.session_state.manager.current_context)