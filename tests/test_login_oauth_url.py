"""
The Google sign-in button built an authorize URL with no `prompt`, so Google
was free to resolve the account itself via an authuser index. In a browser
signed into more than one Google account that guess can miss, and Google
answers with a bare infrastructure page:

    403. That's an error.
    We're sorry, but you do not have access to this page. That's all we know.

No OAuth error code, no styled "Access blocked" screen — nothing pointing at
the cause. Incognito worked because a fresh profile has one account to pick.
"""
from urllib.parse import parse_qs, quote, urlparse


def build_oauth_url(supabase_url: str, callback_url: str) -> str:
    """Mirrors views/login.py's construction."""
    return (
        f"{supabase_url}/auth/v1/authorize"
        f"?provider=google"
        f"&redirect_to={quote(callback_url, safe='')}"
        f"&prompt=select_account"
    )


SUPA = "https://proj.supabase.co"
APP = "https://my-stylist.streamlit.app"


class TestAuthorizeUrl:
    def test_forces_the_account_chooser(self):
        q = parse_qs(urlparse(build_oauth_url(SUPA, APP)).query)
        assert q["prompt"] == ["select_account"], "multi-account browsers 403 without this"

    def test_still_asks_for_google(self):
        q = parse_qs(urlparse(build_oauth_url(SUPA, APP)).query)
        assert q["provider"] == ["google"]

    def test_redirect_target_round_trips(self):
        q = parse_qs(urlparse(build_oauth_url(SUPA, APP)).query)
        assert q["redirect_to"] == [APP]

    def test_redirect_target_is_encoded_not_split(self):
        """An unencoded redirect_to would break the query string apart."""
        url = build_oauth_url(SUPA, "https://app.example.com/?a=1&b=2")
        q = parse_qs(urlparse(url).query)
        assert q["redirect_to"] == ["https://app.example.com/?a=1&b=2"]
        assert set(q) == {"provider", "redirect_to", "prompt"}, "no leaked params"

    def test_hits_the_authorize_endpoint(self):
        assert urlparse(build_oauth_url(SUPA, APP)).path == "/auth/v1/authorize"

    def test_no_pkce_challenge(self):
        """Implicit flow on purpose: Streamlit loses memory between redirect legs."""
        q = parse_qs(urlparse(build_oauth_url(SUPA, APP)).query)
        assert "code_challenge" not in q

    def test_localhost_default_still_builds(self):
        q = parse_qs(urlparse(build_oauth_url(SUPA, "http://localhost:8501")).query)
        assert q["redirect_to"] == ["http://localhost:8501"]
        assert q["prompt"] == ["select_account"]


def test_source_actually_carries_the_parameter():
    """Guards against the URL being edited without the fix."""
    src = open("views/login.py").read()
    assert "prompt=select_account" in src
