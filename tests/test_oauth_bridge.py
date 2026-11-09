"""
Supabase's implicit flow returns the session in the URL fragment, which the
server never sees. Getting it to Python has now been tried three ways against
the deployed app:

  1. rewrite the URL into ?access_token=...&refresh_token=...
     Works, but puts a long-lived refresh token in the address bar, browser
     history, and the hosting proxy's access logs. st.query_params.clear()
     cleans the first two and cannot touch the third.

  2. write it to the sb_session cookie
     Does not work at all. Measured: the cookie is set and present in
     document.cookie, and a full reload with it present still rendered the login
     form — st.context.cookies does not see it on Streamlit Cloud.

  3. return it as a component value (this)
     Travels over the existing websocket. Never in a URL, so nothing to leak
     into logs or history.
"""
import re

import pytest

BRIDGE_JS = open("components/oauth_bridge/frontend/index.html").read()
BRIDGE_PY = open("components/oauth_bridge/__init__.py").read()
APP_SRC = open("app.py").read()
APP_CODE = "\n".join(l for l in APP_SRC.splitlines() if not l.strip().startswith("#"))


class TestTokensNeverEnterAUrl:
    def test_bridge_does_not_build_token_query_params(self):
        assert "searchParams.set" not in BRIDGE_JS

    def test_app_no_longer_rewrites_the_url_with_tokens(self):
        assert "searchParams.set('access_token'" not in APP_CODE
        assert "searchParams.set('refresh_token'" not in APP_CODE

    def test_bridge_does_not_write_a_cookie(self):
        assert ".cookie" not in BRIDGE_JS

    def test_bridge_navigates_nothing(self):
        """Navigation is what the Cloud sandbox restricts; the bridge avoids it."""
        assert "location.replace" not in BRIDGE_JS
        assert "location.href =" not in BRIDGE_JS


class TestBridgeBehaviour:
    def test_reads_the_parent_frame_hash(self):
        assert "window.parent || window" in BRIDGE_JS
        assert "location.hash" in BRIDGE_JS

    def test_returns_both_tokens(self):
        assert "access_token" in BRIDGE_JS and "refresh_token" in BRIDGE_JS
        assert "setComponentValue" in BRIDGE_JS

    def test_resends_once_to_survive_the_registration_race(self):
        """Matches the fix already proven necessary in inspiration_board."""
        assert "setTimeout" in BRIDGE_JS
        assert re.search(r"}, 600\)", BRIDGE_JS)

    def test_clears_the_fragment_without_navigating(self):
        assert "history.replaceState" in BRIDGE_JS

    def test_declares_zero_height(self):
        assert "setFrameHeight" in BRIDGE_JS

    def test_python_wrapper_returns_none_by_default(self):
        assert "default=None" in BRIDGE_PY


class TestAppConsumesTheBridge:
    def test_app_imports_and_calls_it(self):
        assert "from components.oauth_bridge import oauth_bridge" in APP_CODE
        assert "_oauth_tokens = oauth_bridge()" in APP_CODE

    def test_sets_the_session_from_the_component_value(self):
        assert '_oauth_tokens["access_token"]' in APP_CODE
        assert '_oauth_tokens["refresh_token"]' in APP_CODE

    def test_legacy_query_param_path_still_clears_on_failure(self):
        """A bookmarked old callback must not leave tokens sitting in the URL."""
        block = APP_CODE[APP_CODE.index('if "access_token" in query_params'):]
        block = block[:block.index("GATE 1") if "GATE 1" in block else len(block)]
        assert block.count("st.query_params.clear()") >= 2, (
            "clear on the failure path too, not just on success"
        )
