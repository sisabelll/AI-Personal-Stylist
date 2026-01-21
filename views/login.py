import streamlit as st
import time

def render_login(supabase):
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
            
            submit_login = st.form_submit_button("Log In", use_container_width=True)
            
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
                                st.success("Welcome back! Loading your profile...")
                                time.sleep(1)
                                st.rerun() # Refresh app to show the main interface
                                
                    except Exception as e:
                        # Friendly error message
                        st.error(f"Login failed: {str(e)}")

    # --- TAB 2: SIGN UP (New Users) ---
    with tab2:
        with st.form("signup_form"):
            new_email = st.text_input("Email", placeholder="you@example.com")
            new_password = st.text_input("Password", type="password", help="Must be at least 6 characters")
            confirm_password = st.text_input("Confirm Password", type="password")
            
            submit_signup = st.form_submit_button("Create Account", use_container_width=True)
            
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

    # --- OPTIONAL: GOOGLE OAUTH SECTION ---
    # st.markdown("---")
    # st.markdown("### Or continue with")
    
    # if st.button("Google", use_container_width=True):
    #     try:
    #         # Detect where the app is running (Localhost vs. Cloud)
    #         # You must set APP_URL in .streamlit/secrets.toml for cloud deployment
    #         # Default to localhost for testing
    #         callback_url = st.secrets.get("APP_URL", "http://localhost:8501")
            
    #         response = supabase.auth.sign_in_with_oauth({
    #             "provider": "google",
    #             "options": {
    #                 "redirectTo": callback_url
    #             }
    #         })
            
    #         # OAuth requires a browser redirect
    #         if response.url:
    #             st.markdown(f'<meta http-equiv="refresh" content="0;url={response.url}">', unsafe_allow_html=True)
                
    #     except Exception as e:
    #         st.error(f"Google Login Error: {e}")