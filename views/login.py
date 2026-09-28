import json
import os
import streamlit as st
import streamlit.components.v1 as st_components
import time
from urllib.parse import quote

def render_login(supabase, on_login=None):
    """
    Renders the Login/Signup UI.
    Handles authentication via Supabase and updates st.session_state.
    """
    
    # Optional: minimal styling to center things
    st.markdown("""
        <style>
            .stTabs [data-baseweb="tab-list"] { justify-content: center; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("## 🔐 Login to AI Stylist", unsafe_allow_html=True)
    st.caption("Sign in to access your digital closet and personalized style profile.")

    # Create Tabs
    tab1, tab2 = st.tabs(["Log In", "Create Account"])

    # --- TAB 1: LOGIN (Returning Users) ---
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            
            submit_login = st.form_submit_button("Log In", width='stretch')
            
            if submit_login:
                if not email or not password:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        with st.spinner("Logging in..."):
                            # 1. Supabase Auth Call
                            response = supabase.auth.sign_in_with_password({
                                "email": email, 
                                "password": password
                            })
                            
                            # 2. Success Handling
                            if response.user:
                                st.session_state["session"] = response.session
                                st.session_state["user"] = response.user
                                st.session_state["user_id"] = response.user.id
                                if on_login:
                                    on_login(response.session)
                                st.success("Welcome back! Loading your profile...")
                                time.sleep(1)
                                st.rerun()
                                
                    except Exception as e:
                        # Friendly error message
                        st.error(f"Login failed: {str(e)}")

    # --- TAB 2: SIGN UP (New Users) ---
    with tab2:
        with st.form("signup_form"):
            new_email = st.text_input("Email", placeholder="you@example.com")
            new_password = st.text_input("Password", type="password", help="Must be at least 6 characters")
            confirm_password = st.text_input("Confirm Password", type="password")
            
            submit_signup = st.form_submit_button("Create Account", width='stretch')
            
            if submit_signup:
                if new_password != confirm_password:
                    st.error("Passwords do not match!")
                elif len(new_password) < 6:
                    st.error("Password is too short (min 6 chars).")
                else:
                    try:
                        with st.spinner("Creating account..."):
                            # 1. Supabase Sign Up Call
                            response = supabase.auth.sign_up({
                                "email": new_email, 
                                "password": new_password
                            })
                            
                            # 2. Check for "Confirm Email" requirement
                            # (Supabase defaults to requiring email confirmation unless you disable it)
                            if response.user and response.user.identities == []:
                                st.warning("Account created! Please check your email to confirm your address before logging in.")
                            elif response.user:
                                st.success("Account created successfully! You are now logged in.")
                                st.session_state["user"] = response.user
                                st.session_state["user_id"] = response.user.id
                                time.sleep(1)
                                st.rerun()
                                
                    except Exception as e:
                        st.error(f"Sign up failed: {str(e)}")

    # --- GOOGLE OAUTH ---
    st.markdown("---")
    st.markdown("<p style='text-align:center;color:#888;font-size:0.85rem;margin-bottom:0.5rem'>or continue with</p>", unsafe_allow_html=True)

    # Build the Supabase OAuth URL manually — no PKCE code_challenge — so
    # Supabase uses the implicit flow and returns tokens in the URL hash rather
    # than requiring a PKCE code exchange (which breaks in Streamlit because the
    # server restarts between redirect legs and loses the verifier).
    supabase_url = os.getenv("SUPABASE_URL", "")
    callback_url = os.getenv("APP_URL", "http://localhost:8501")
    oauth_url = (
        f"{supabase_url}/auth/v1/authorize"
        f"?provider=google"
        f"&redirect_to={quote(callback_url, safe='')}"
        f"&prompt=select_account"
    )

    # A real link, not a button that injects JS.
    #
    # Streamlit Cloud serves the app inside a wrapper iframe whose sandbox is
    # "allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox
    # allow-same-origin allow-scripts allow-downloads" — note there is no
    # allow-top-navigation. So the old approach (inject a script that calls
    # location.replace on the parent/top) could not move the tab: navigating the
    # frame itself loaded accounts.google.com framed, and Google refuses to be
    # framed, answering with a bare "403. That's an error ... That's all we
    # know." Retargeting it at window.top then threw SecurityError outright.
    #
    # allow-popups IS granted, and allow-popups-to-escape-sandbox means the new
    # tab is a clean, unsandboxed context. A link the user actually clicks
    # carries the user activation a popup needs; a script injected after a
    # Streamlit rerun has none, which is why the old code was blocked either way.
    #
    # Verified in the deployed app: clicking through this path reaches the Google
    # account chooser and completes the round trip.
    st.link_button(
        "Continue with Google",
        oauth_url,
        use_container_width=True,
    )