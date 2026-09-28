"""
Google sign-in returned a bare 403 on the deployed app, and the earlier
"navigate window.top" fix then threw SecurityError instead.

Both failures are the same constraint. Streamlit Cloud serves the app inside a
wrapper iframe (my-stylist.streamlit.app/~/+/) whose sandbox is, read from the
live page:

    allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox
    allow-same-origin allow-scripts allow-downloads

There is no allow-top-navigation. So:

  * navigating the frame itself loaded accounts.google.com framed, and Google
    refuses to be framed -> "403. That's an error ... That's all we know."
  * navigating window.top threw
    "Unsafe attempt to initiate navigation for frame with URL ... The frame
     attempting navigation of the top-level window is sandboxed".

allow-popups IS granted, and a link the user actually clicks carries the user
activation a popup needs — a script injected after a Streamlit rerun has none.
So the outbound leg is a real anchor (st.link_button), and the return leg never
navigates at all: it writes the session cookie Python already reads and reloads
only its own frame.

None of this reproduces locally, where there is no wrapper frame.
"""
import re

import pytest

LOGIN_SRC = open("views/login.py").read()
APP_SRC = open("app.py").read()

# Code, not the comments that explain the history.
LOGIN_CODE = "\n".join(l for l in LOGIN_SRC.splitlines() if not l.strip().startswith("#"))
APP_CODE = "\n".join(l for l in APP_SRC.splitlines() if not l.strip().startswith("#"))


class TestOutboundLegIsARealLink:
    def test_uses_link_button(self):
        assert "st.link_button(" in LOGIN_CODE, (
            "the sign-in must be an anchor the user clicks; a script injected after "
            "a rerun has no user activation and the popup is blocked"
        )

    def test_does_not_inject_a_navigation_script(self):
        assert "location.replace" not in LOGIN_CODE
        assert "createElement('script')" not in LOGIN_CODE

    def test_link_points_at_the_built_oauth_url(self):
        m = re.search(r"st\.link_button\(\s*\"Continue with Google\",\s*(\w+)", LOGIN_CODE)
        assert m and m.group(1) == "oauth_url"


class TestReturnLegNeverNavigates:
    def test_does_not_navigate_the_top_window(self):
        assert "top_.location.replace" not in APP_CODE
        assert "window.top.location.replace" not in APP_CODE

    def test_reads_the_hash_but_only_reads(self):
        """Reading across same-origin frames is fine; navigating is not."""
        assert "top_.location.hash" in APP_CODE

    def test_hands_tokens_over_via_the_session_cookie(self):
        assert "parentDoc.cookie" in APP_CODE
        assert "access_token" in APP_CODE and "refresh_token" in APP_CODE

    def test_reloads_only_its_own_frame(self):
        assert "window.location.reload()" in APP_CODE, (
            "self-navigation is the one move no sandbox flag restricts"
        )

    def test_clears_tokens_from_the_address_bar_without_navigating(self):
        assert "history.replaceState" in APP_CODE

    def test_cookie_name_and_ttl_come_from_the_python_constants(self):
        """
        The JS writes the cookie Python reads, so the two must not drift apart.
        The snippet is an f-string, so the source carries the interpolation
        placeholders rather than the literal values — assert on those.
        """
        assert re.search(r'_COOKIE_NAME\s*=\s*"[^"]+"', APP_SRC), "missing _COOKIE_NAME"
        assert re.search(r"_COOKIE_TTL_DAYS\s*=\s*\d+", APP_SRC), "missing _COOKIE_TTL_DAYS"
        assert '"{_COOKIE_NAME}=" +' in APP_SRC, "JS must interpolate the Python cookie name"
        assert "max-age={_COOKIE_TTL_DAYS * 86400}" in APP_SRC, "JS must interpolate the Python TTL"


class TestNoInjectedNavigationSurvivesAnywhere:
    """The defect class: any injected script that moves a window above this frame."""

    NAV_RE = re.compile(r"s\.textContent\s*=\s*[\"']([^\"']*)[\"']")

    @pytest.mark.parametrize("name,src", [("views/login.py", LOGIN_CODE), ("app.py", APP_CODE)])
    def test_injected_scripts_do_not_navigate_an_ancestor(self, name, src):
        for m in self.NAV_RE.finditer(src):
            body = m.group(1)
            assert "location.replace" not in body, (
                f"{name} injects an ancestor navigation ({body!r}); the Cloud sandbox "
                "blocks it and Google 403s when framed"
            )


class TestSignInUrlUnchanged:
    """The URL was never the problem — don't regress what was already right."""

    def test_forces_the_account_chooser(self):
        assert "prompt=select_account" in LOGIN_SRC

    def test_uses_implicit_flow(self):
        m = re.search(r"oauth_url = \((.*?)\)", LOGIN_SRC, re.S)
        assert m and "code_challenge" not in m.group(1)

    def test_uses_the_configured_app_url(self):
        assert "APP_URL" in LOGIN_SRC
