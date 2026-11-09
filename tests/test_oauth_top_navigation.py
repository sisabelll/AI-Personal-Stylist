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


class TestReturnLegDoesNotNavigateAtAll:
    """
    The return leg moved to components/oauth_bridge, which hands the tokens over
    the websocket. app.py no longer rewrites any URL, so there is nothing here
    for the Cloud sandbox to block and no token to leak into a URL.
    Behaviour of the bridge itself is covered by tests/test_oauth_bridge.py.
    """

    def test_app_does_not_inject_a_token_navigation(self):
        assert "searchParams.set('access_token'" not in APP_CODE
        assert "searchParams.set('refresh_token'" not in APP_CODE

    def test_app_delegates_to_the_bridge(self):
        assert "_oauth_tokens = oauth_bridge()" in APP_CODE

    def test_no_top_window_navigation_anywhere(self):
        assert "window.top" not in APP_CODE


class TestNoInjectedNavigationSurvivesAnywhere:
    """The defect class: any injected script that moves a window above this frame."""

    NAV_RE = re.compile(r"s\.textContent\s*=\s*[\"']([^\"']*)[\"']")

    @pytest.mark.parametrize("name,src", [("views/login.py", LOGIN_CODE), ("app.py", APP_CODE)])
    def test_injected_scripts_never_target_the_top_window(self, name, src):
        """
        Self-navigation is fine and is what the return leg depends on. What the
        sandbox forbids is reaching above the app frame — window.top or
        window.parent from inside the frame's own injected script.
        """
        for m in self.NAV_RE.finditer(src):
            body = m.group(1)
            assert "window.top" not in body, (
                f"{name} injects a top-window navigation ({body!r}); the Cloud "
                "wrapper frame is sandboxed without allow-top-navigation and it "
                "throws SecurityError"
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


class TestSessionCookieIsSecureOverHttps:
    """
    The cookie carries a Supabase bearer token. Without ;Secure the browser
    sends it over plaintext HTTP too. Flagged by automated review on the return
    leg; the two pre-existing write sites had the same gap.

    Conditional rather than unconditional: a Secure cookie is silently dropped
    on http://localhost, which would break local development.
    """

    @staticmethod
    def _write_sites():
        """Assignments to document.cookie — not st.context.cookies.get() reads."""
        return [l for l in APP_SRC.splitlines()
                if "_COOKIE_NAME" in l and (".cookie=" in l or ".cookie =" in l)]

    def test_both_write_sites_are_found(self):
        """
        Guards the loop below against passing vacuously. Two sites: the clear
        and the set in the _save_session_cookie flush. The OAuth return leg used
        to add a third, but it no longer writes a cookie at all — st.context.cookies
        cannot read it on Streamlit Cloud, so it stored a bearer token for nothing.
        """
        assert len(self._write_sites()) == 2, self._write_sites()

    def test_every_cookie_write_can_set_secure(self):
        lines = APP_SRC.splitlines()
        for w in self._write_sites():
            i = lines.index(w)
            window = "\n".join(lines[max(0, i - 3):i + 3])
            assert "Secure" in window, f"cookie write without a Secure guard: {w.strip()[:70]}"

    def test_secure_is_conditional_on_https(self):
        assert APP_SRC.count("location.protocol === 'https:'") + \
               APP_SRC.count('location.protocol === "https:"') >= 2, (
            "Secure must be gated on HTTPS so localhost still works"
        )

    def test_samesite_still_set(self):
        assert "SameSite=Lax" in APP_SRC
