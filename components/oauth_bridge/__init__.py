import os
from typing import Optional

import streamlit.components.v1 as components

# Vanilla JS component — no build step, same pattern as inspiration_board.
_frontend = os.path.join(os.path.dirname(__file__), "frontend")
_component = components.declare_component("oauth_bridge", path=_frontend)


def oauth_bridge(key: Optional[str] = "oauth_bridge") -> Optional[dict]:
    """
    Carry Supabase's implicit-flow tokens from the URL fragment to Python.

    Supabase returns the session in the URL hash, which the server never sees.
    The obvious workarounds both fail on Streamlit Cloud, where the app runs
    inside a sandboxed wrapper iframe:

      * rewriting the URL into query params puts a long-lived refresh token in
        the address bar, browser history, and the hosting proxy's access logs
      * writing a cookie does not help either — st.context.cookies cannot read
        it there, verified against the deployed app

    This returns the tokens as a component value, so they travel over the
    existing websocket and never appear in a URL at all.

    Returns {"access_token": str, "refresh_token": str} or None.
    """
    return _component(key=key, default=None)
