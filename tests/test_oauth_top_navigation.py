"""
"Continue with Google" returned a bare Google error on the deployed app:

    403. That's an error.
    We're sorry, but you do not have access to this page. That's all we know.

No OAuth error code, no styled "Access blocked" screen — so it read like the
client, the consent screen, or the account was misconfigured. All of those were
verified healthy four times.

The real cause, confirmed by driving the deployed app in a real browser: on
Streamlit Cloud the app runs inside a wrapper iframe
(my-stylist.streamlit.app/~/+/). The injected redirect script ran
`window.location.replace(...)`, where `window` is that frame, not the tab. So
Google's sign-in page was requested INSIDE an iframe, and Google refuses to be
framed — X-Frame-Options on accounts.google.com answers with that bare 403.

Measured in the browser at the moment of failure:

    top window URL : https://my-stylist.streamlit.app/     (never navigated)
    app frame      : cross-origin SecurityError            (had gone to Google)
    window === top : False

Navigating `window.top` instead produced the account chooser.

Locally there is no wrapper frame — `window` IS the tab — so this could only
ever fail once deployed, which is why every local test passed.
"""
import re

import pytest

LOGIN_SRC = open("views/login.py").read()
APP_SRC = open("app.py").read()

# The lines that inject a navigation into the parent document.
NAV_RE = re.compile(r"s\.textContent\s*=\s*'([^']*location\.replace[^']*)'")


def injected_navigations():
    found = []
    for name, src in (("views/login.py", LOGIN_SRC), ("app.py", APP_SRC)):
        for m in NAV_RE.finditer(src):
            found.append((name, m.group(1)))
    return found


class TestEveryInjectedNavigationTargetsTheTopWindow:
    def test_both_injection_sites_are_present(self):
        """Guards against the assertions below passing vacuously."""
        found = injected_navigations()
        names = {n for n, _ in found}
        assert names == {"views/login.py", "app.py"}, f"expected both sites, got {found}"

    @pytest.mark.parametrize("name,snippet", injected_navigations(),
                             ids=[f"{n}:{i}" for i, (n, _) in enumerate(injected_navigations())])
    def test_navigation_escapes_the_wrapper_frame(self, name, snippet):
        assert "window.top" in snippet, (
            f"{name} navigates its own frame. On Streamlit Cloud that frame is the "
            "app wrapper, so Google's sign-in loads framed and returns a bare 403."
        )

    @pytest.mark.parametrize("name,snippet", injected_navigations(),
                             ids=[f"{n}:{i}" for i, (n, _) in enumerate(injected_navigations())])
    def test_falls_back_when_there_is_no_wrapper(self, name, snippet):
        """Locally window.top IS window; the expression must still work."""
        assert "|| window" in snippet, f"{name} should fall back to window when top is absent"

    @pytest.mark.parametrize("name,snippet", injected_navigations(),
                             ids=[f"{n}:{i}" for i, (n, _) in enumerate(injected_navigations())])
    def test_bare_window_location_replace_is_gone(self, name, snippet):
        assert not re.search(r"(?<![.\w])window\.location\.replace", snippet), (
            f"{name} still has a bare window.location.replace"
        )


class TestSignInUrlIsUnchanged:
    """The 403 was never about the URL — don't regress what was already correct."""

    def test_still_forces_the_account_chooser(self):
        assert "prompt=select_account" in LOGIN_SRC

    def test_still_uses_implicit_flow(self):
        """
        No PKCE challenge in the built URL. Checked against the URL construction
        only — login.py's comment mentions code_challenge to explain its absence,
        so a naive substring search over the whole file matches the prose.
        """
        m = re.search(r"oauth_url = \((.*?)\)", LOGIN_SRC, re.S)
        assert m, "could not locate the oauth_url construction"
        assert "code_challenge" not in m.group(1)

    def test_still_passes_the_configured_app_url(self):
        assert "APP_URL" in LOGIN_SRC
