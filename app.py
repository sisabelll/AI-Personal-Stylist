import streamlit as st
import json
import os
from dotenv import load_dotenv

from agents.style_researcher import StyleResearcherAgent
from workflow.manager import ConversationManager
from core.client import OpenAIClient
from services.storage import DataLoader

load_dotenv()

# 1. PAGE CONFIGURATION
st.set_page_config(page_title="AI Personal Stylist", page_icon="🎨", layout="wide")

# 2. LOAD DATA (Cached so it doesn't reload on every click)
@st.cache_resource
def get_static_data():
    base_dir = '.'
    data = DataLoader(base_dir)
    return data

style_rules = get_static_data().style_rules

# 3. SIDEBAR: THE "LITE" ONBOARDING
with st.sidebar:
    st.sidebar.header("Developer Tools")
    dev_mode = st.sidebar.checkbox("⚡ Use Cached Initial Outfit", value=True)
    
    st.header("👤 User Profile Simulator")
    st.info("Tweak these to test different user personas.")

    # Dynamic Inputs for the Profile
    selected_name = st.text_input("Name", value="Isabel")
    
    # Dropdowns for Hard Constraints
    wear_pref = st.selectbox("Wear Preference", ["Womenswear", "Menswear", "Unisex"])
    body_type = st.selectbox("Body Essence", ["straight_type", "wave_type", "natural_type"])
    color_season = st.selectbox("Color Season", ["spring_warm_tone", "summer_cool_tone", "autumn_warm_tone", "winter_cool_tone"])
    
    # The "Researcher" Trigger
    style_icon = st.text_input("Style Icon (Triggers Researcher)", value="Bae Suzy")
    cleaned_style_icon = StyleResearcherAgent(OpenAIClient())._sanitize_entity(style_icon)

    dynamic_profile = {
        "name": selected_name,
        "wear_preference": wear_pref,
        "body_style_essence": body_type,
        "personal_color": color_season,
        "style_references": [cleaned_style_icon] if cleaned_style_icon else []
    }

    # Button to Apply Changes
    if st.button("🔄 Reset / Apply Profile"):
        # 1. Create a Status Container in the MAIN app area (not sidebar) for visibility
        with st.chat_message("assistant"):
            with st.status("⚙️ Syncing Profile...", expanded=True) as status_box:
                
                # Define the Callback
                def sidebar_updater(msg):
                    st.write(msg) # Writes inside the status box
                
                # 2. Initialize Manager if needed
                if st.session_state.manager is None:
                    # (Init code from before...)
                    client = OpenAIClient()
                    st.session_state.manager = ConversationManager(client=client, user_profile=dynamic_profile, style_rules=style_rules)

                # 3. Call the NEW Manager Method
                summary_response = st.session_state.manager.update_profile_and_research(
                    new_profile_data=dynamic_profile,
                    status_callback=sidebar_updater
                )
                
                status_box.update(label="✅ Profile Synced!", state="complete", expanded=False)
                
        # 4. Display the Summary
        st.markdown(summary_response)
        
        # 5. Update Session State
        # We add the summary to history so it stays on screen
        st.session_state.messages.append({"role": "assistant", "content": summary_response})

# 4. INITIALIZE STATE (The Brain)
if "messages" not in st.session_state:
    st.session_state.messages = []

# Track if we have run the initial setup yet
if "session_started" not in st.session_state:
    st.session_state.session_started = False

if "manager" not in st.session_state or st.session_state.manager is None:
    # Build the User Profile object from Sidebar inputs
    dynamic_profile = {
        "name": selected_name,
        "wear_preference": wear_pref,
        "body_style_essence": body_type,
        "personal_color": color_season,
        "style_references": [cleaned_style_icon] if cleaned_style_icon else []
    }
    
    # Initialize your Backend Components
    # We pass 'None' for context initially; the manager will handle the first request
    client = OpenAIClient()
    data = get_static_data()
   
    st.session_state.manager = ConversationManager(
        client=client,
        user_profile=dynamic_profile,
        style_rules=style_rules,
        request_context_schema=data.request_context
    )
    
    # Add a welcome message
    # Map the technical names to display names for better UX
    color_display = {
        "spring_warm_tone": "Spring Warm",
        "summer_cool_tone": "Summer Cool", 
        "autumn_warm_tone": "Autumn Warm",
        "winter_cool_tone": "Winter Cool"
    }.get(color_season, color_season)
    
    body_display = {
        "straight_type": "Straight",
        "wave_type": "Wave",
        "natural_type": "Natural"
    }.get(body_type, body_type)
    
    welcome_msg = f"Hello {selected_name}! I see you're a **{color_display} {body_display}**. How can I help you dress today?"
    st.session_state.messages.append({"role": "assistant", "content": welcome_msg})
    
    # Ensure flag is false on reset
    st.session_state.session_started = False

# 5. MAIN CHAT INTERFACE
st.title("Your AI Stylist MVP")

# A. Display Chat History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# B. Handle User Input
if prompt := st.chat_input("Ex: I have a holiday party and want to wear my black skirt..."):
    st.session_state.last_query = prompt

    # 1. Display User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Generate AI Response
    with st.chat_message("assistant"):
        with st.status("🧠 Thinking... (Checking Style Rules & Researching)", expanded=True) as status_box:
            def ui_updater(message):
                st.write(message)

            try:
                if not st.session_state.session_started:
                    # CASE A: SETUP
                    response_text = st.session_state.manager.start_new_session(
                        user_request_context={}, 
                        user_query=prompt,
                        status_callback=ui_updater,
                        use_cache=dev_mode
                    )
                    st.session_state.session_started = True 
                    
                else:
                    # CASE B: REFINEMENT
                    # (You can also add status_callback to refine_session if you want!)
                    st.write("👂 Listening to feedback...")
                    response_text = st.session_state.manager.refine_session(prompt)
                
                # Update status to "Complete" (Colourizes it green)
                status_box.update(label="✨ Recommendation Ready!", state="complete", expanded=False)
                
                # Show the final text
                st.markdown(response_text)
                st.session_state.messages.append({"role": "assistant", "content": response_text})
                
            except Exception as e:
                status_box.update(label="❌ Error", state="error")
                st.error(f"Something went wrong: {e}")

# 6. DEBUG EXPANDER (Optional but recommended)
with st.expander("🕵️‍♀️ Developer Debug View"):
    if st.session_state.manager:
        st.write("Current Context:", st.session_state.manager.current_context)
        st.write("Anchored Items:", st.session_state.manager.conversation_state.get('anchored_items'))


def display_outfit_recommendation(response_data):
    # 1. RENDER TEXT IMMEDIATELY (Zero Latency)
    st.markdown(response_data.get('reasoning', "Here is a look for you:"))
    
    outfit_items = response_data['outfit_options'][0]['items']
    
    # 2. FETCH IMAGES IN PARALLEL (Background)
    # This runs while the user is reading the text above.
    with st.spinner("🛍️ Scanning stores for matches..."):
        visuals_map = st.session_state.catalog.search_products_parallel(outfit_items)

    # 3. RENDER THE VISUAL GRID
    st.divider()
    cols = st.columns(len(outfit_items))
    
    for idx, item in enumerate(outfit_items):
        with cols[idx]:
            product = visuals_map.get(item.item_name)
            
            if product and product.get('image'):
                st.image(product['image'], use_container_width=True)
                st.caption(f"[{product['title'][:20]}...]({product['link']})")
                st.caption(f"**{product.get('price', '')}**")
            else:
                # Fallback if search fails
                st.info(f"🔎 {item.item_name}")
            
            st.markdown(f"**{item.category}**")