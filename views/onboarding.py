import streamlit as st
from datetime import date
import time

def clean_text(text):
    """Removes extra spaces and handles empty strings."""
    if not text:
        return None
    text = text.strip()
    return text if text else None

def clean_list(text_input):
    """Splits commas, strips spaces, removes duplicates and empties."""
    if not text_input:
        return []
    # 1. Split by comma
    items = text_input.split(",")
    # 2. Strip spaces and filter empty strings
    cleaned = [x.strip() for x in items if x.strip()]
    # 3. Remove duplicates (using set) while keeping order
    return list(dict.fromkeys(cleaned))

def render_onboarding(storage, user_id):
    if "profile_check_done" not in st.session_state:
        with st.spinner("Checking your account status..."):
            existing_profile = storage.get_profile(user_id)
            
            if existing_profile:
                # 🟢 FOUND THEM! Load data and skip form.
                st.session_state["user_profile"] = existing_profile
                st.session_state["profile_complete"] = True
                st.session_state["profile_check_done"] = True
                st.rerun() # Restart app to go straight to Stylist
            else:
                # 🔴 NEW USER. Mark check as done so we show form.
                st.session_state["profile_check_done"] = True

    st.markdown("## ✨ Let's Build Your Style Profile")
    st.markdown("Help me understand your vibe, so I can stop guessing and start styling.")

    with st.form("onboarding_form"):
        
        # --- 1. THE CONTEXT (Who & Where) ---
        st.caption("1. THE CONTEXT")
        col1, col2 = st.columns(2)
        
        with col1:
            full_name = st.text_input("Name", placeholder="e.g. Isabel")
            # Using Date Input for accuracy
            birth_date = st.date_input(
                "Birthday", 
                min_value=date(1950, 1, 1), 
                max_value=date(2015, 12, 31),
                value=date(1995, 6, 15)
            )
        
        with col2:
            location_city = st.text_input("City", placeholder="e.g. New York, NY")

        st.markdown("---")

        # --- 2. THE CANVAS (Body & Size) ---
        st.caption("2. THE CANVAS")
        
        # A. Physical Stats
        c1, c2, c3 = st.columns(3)
        with c1:
            height_cm = st.number_input("Height (cm)", min_value=100, max_value=250, value=165)
        with c2:
            body_style_essence = st.selectbox(
                "Body Essence", 
                ["Straight", "Wave", "Natural", "Not sure / Skip"]
            )
        with c3:
            color_season = st.selectbox(
                "Color Season", 
                ["Spring Warm", "Summer Cool", "Autumn Warm", "Winter Cool", "Not Sure / Skip"]
            )
        
        # B. Sizing (New Section)
        st.markdown("**Your Typical Sizes**")
        s1, s2, s3 = st.columns(3)
        with s1:
            size_top = st.selectbox("Top Size", ["XS", "S", "M", "L", "XL", "XXL"], index=2)
        with s2:
            size_bottom = st.text_input("Bottom Size", placeholder="e.g. 26, 4, M")
        with s3:
            size_shoe = st.text_input("Shoe Size", placeholder="e.g. US 7, EU 38, KR 235")
        
        # WEAR PREFERENCE (Critical for Search)
        wear_preference = st.radio(
            "I mostly wear:", 
            ["Womenswear", "Menswear", "Unisex"], 
            horizontal=True
        )

        st.markdown("---")

        # --- 3. THE VIBE (Inspiration) ---
        st.caption("3. THE VIBE")
        
        # SECTION A: ICONS
        st.markdown("**Who are your Style Icons?** (People)")
        st.caption("Celebrities, influencers, or fictional characters whose style you admire.")
        style_icons_input = st.text_input("Examples: Bae Suzy, Bella Hadid, Zoë Kravitz", key="icons")

        # SECTION B: BRANDS (The Logic we just discussed)
        st.markdown("**Which Brands inspire you?**")
        st.caption("Even if you don't own them yet—which brands represent your goal aesthetic?")
        brands_input = st.text_input("Examples: The Row, Miu Miu, Arket, Cos", key="brands")

        # SECTION C: KEYWORDS
        st.markdown("**Describe your goal aesthetic:**")
        aesthetic_keywords = st.multiselect(
            "Select up to 5",
            [
                "Minimalist", "Streetwear", "Old Money", "Y2K", "Coquette", "Boho", 
                "Corporate Chic", "Athleisure", "Grunge", "Preppy", "Avant-Garde", "Scandi"
            ]
        )
        
        # --- 4. THE CONSTRAINTS ---
        st.caption("4. THE REALITY")
        budget_tier = st.select_slider(
            "Typical Budget per Item", 
            options=["$", "$$", "$$$", "$$$$"], 
            value="$$",
            help="$: <$50 | $$: $50-$150 | $$$: $150-$400 | $$$$: Luxury"
        )

        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("Start with a first look ➔", width='stretch')

        if submitted:
            if not full_name or not location_city:
                st.error("Please fill in your Name and City!")
            else:                
                # 1. Clean Profile Data
                final_name = clean_text(full_name).title() # "isabel " -> "Isabel"
                final_city = clean_text(location_city).title() # "nyc" -> "Nyc" (or just keep original)
                final_bottom = clean_text(size_bottom)
                final_shoe = clean_text(size_shoe)

                # 2. Clean Lists (The most important part)
                final_icons = clean_list(style_icons_input)
                final_brands = clean_list(brands_input)
                
                # 🛠️ DATA PACKAGING
                profile_payload = {
                    "full_name": final_name,
                    "birth_date": str(birth_date),
                    "location_city": final_city,
                    "height_cm": height_cm,
                    "body_style_essence": body_style_essence,
                    "color_season": color_season,
                    "wear_preference": wear_preference,
                    "sizes": {
                        "top": size_top,
                        "bottom": final_bottom, 
                        "shoe": final_shoe     
                    }
                }
                
                prefs_payload = {
                    "style_icons": final_icons,     
                    "favorite_brands": final_brands, 
                    "aesthetic_keywords": aesthetic_keywords, 
                    "budget_tier": budget_tier,
                    "avoid_items": [] 
                }

                print(f"DEBUG: Saving Profile for User ID: {user_id}")
                print(f"DEBUG: Profile Data: {profile_payload}")
                print(f"DEBUG: Preferences Data: {prefs_payload}")

                token = st.session_state["session"].access_token

                # 💾 SAVE TO SUPABASE
                with st.spinner("Creating your profile..."):
                    try:
                        storage.save_profile(user_id, profile_payload, prefs_payload, token)
                        new_profile = storage.get_profile(user_id)
                        st.session_state["user_profile"] = new_profile
                        st.session_state["profile_complete"] = True
                        
                        st.success("Profile Saved!")
                        time.sleep(1) # Small pause for UX
                        st.rerun()
                    except Exception as e:
                        st.error(f"Save failed: {e}")