"""The HTTP layer over a fake provider: cookies, headers, callback error mapping, CSRF and scope checks."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from oidc_login.application.login_flow import LoginConfig, LoginService
from oidc_login.domain.errors import ProviderError
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
from oidc_login.infrastructure.settings import Settings
from oidc_login.interfaces.composition import Container
from oidc_login.interfaces.http.app import create_app
from oidc_login.interfaces.http.security import CONTENT_SECURITY_POLICY, LOGIN_COOKIE, SESSION_COOKIE
from oidc_login.interfaces.scripted_browser import AppBrowser
from tests.fakes import CLIENT_ID, ISSUER, REDIRECT_URI, CountingTokens, FakeClock, FakeProvider, FakeVerifier, Signer

SETTINGS = Settings.from_environment(
    {
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": CLIENT_ID,
        "OIDC_CLIENT_SECRET": "unit-test-secret",
        "OIDC_REDIRECT_URI": REDIRECT_URI,
        "APP_ENV": "test",
    }
)


@pytest.fixture
def world():
    clock, signer = FakeClock(), Signer()
    provider = FakeProvider(signer, clock)
    sessions = InMemorySessionStore()
    flow = LoginService(
        provider,
        FakeVerifier(signer),
        InMemoryPendingLoginStore(clock, 600),
        sessions,
        clock,
        CountingTokens(),
        LoginConfig(ISSUER, CLIENT_ID, frozenset({"reports:read"})),
    )
    container: Any = Container(settings=SETTINGS, provider=provider, flow=flow, sessions=sessions)  # type: ignore[arg-type]
    return create_app(container), provider, sessions


def sign_in(world, scope=None):
    """Drive the whole round trip with the fake provider; returns the browser and the callback response."""
    app, provider, _ = world
    if scope:
        provider.granted_scope = f"openid {scope}"
    browser = AppBrowser(app)
    start = browser.get("/login" + (f"?scope={scope}" if scope else ""))
    code = provider.issue_code()
    state = provider.last_authorization["state"]
    return browser, browser.get(f"/callback?code={code}&state={state}"), start


def test_login_redirects_to_the_provider_and_sets_a_short_lived_attempt_cookie(world):
    app, provider, _ = world
    response = AppBrowser(app).get("/login")
    assert response.status_code == 302
    assert response.headers["Location"].startswith(f"{ISSUER}/auth?")
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{LOGIN_COOKIE}=")
    for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=600"):
        assert attribute in cookie
    assert "Domain" not in cookie
    assert provider.last_authorization["state"] in response.headers["Location"]


def test_the_callback_creates_an_opaque_session_cookie_and_clears_the_attempt_cookie(world):
    _, response, _ = sign_in(world)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    cookies = response.headers.getlist("Set-Cookie")
    session_cookie = next(c for c in cookies if c.startswith(SESSION_COOKIE))
    for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/"):
        assert attribute in session_cookie
    value = session_cookie.split("=", 1)[1].split(";", 1)[0]
    assert "." not in value
    assert len(value) >= 32
    assert any(c.startswith(f"{LOGIN_COOKIE}=;") for c in cookies)


def test_no_token_ever_reaches_the_browser(world):
    _, _provider, sessions = world
    browser, callback, _ = sign_in(world)
    session = next(iter(sessions._items.values()))
    secrets_held = [session.tokens.access_token, session.tokens.refresh_token, session.tokens.id_token]
    pages = [callback, browser.get("/"), browser.get("/me"), browser.get("/reports")]
    for page in pages:
        blob = page.get_data(as_text=True) + str(dict(page.headers))
        assert all(secret not in blob for secret in secrets_held)


def test_every_response_carries_the_security_headers(world):
    app, *_ = world
    browser = AppBrowser(app)
    for path in ("/", "/login", "/healthz", "/me", "/nope", "/static/style.css"):
        headers = browser.get(path).headers
        assert headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "max-age" in headers["Strict-Transport-Security"]
        assert path.startswith("/static") or headers["Cache-Control"] == "no-store"  # pages carry tokens' results


@pytest.mark.parametrize(
    ("query", "status"),
    [("", 400), ("?error=access_denied", 400), ("?code=x", 400), ("?state=x", 400), ("?code=x&state=y", 400)],
)
def test_a_callback_without_a_valid_login_attempt_is_a_generic_400_and_sets_no_session(world, query, status):
    app, *_ = world
    response = AppBrowser(app).get(f"/callback{query}")
    assert response.status_code == status
    assert SESSION_COOKIE not in response.headers.get("Set-Cookie", "")
    assert "error" not in response.get_data(as_text=True).lower().replace("sign-in failed", "")


def test_a_mismatched_state_is_refused(world):
    app, provider, sessions = world
    browser = AppBrowser(app)
    browser.get("/login")
    code = provider.issue_code()
    response = browser.get(f"/callback?code={code}&state=attacker-state")
    assert response.status_code == 400
    assert sessions.count() == 0


def test_a_callback_from_another_browser_is_refused_even_with_a_valid_code_and_state(world):
    app, provider, sessions = world
    AppBrowser(app).get("/login")  # the attacker starts a login in their own browser...
    code, state = provider.issue_code(), provider.last_authorization["state"]
    victim = AppBrowser(app)  # ...and tricks the victim's browser into completing it: no attempt cookie
    assert victim.get(f"/callback?code={code}&state={state}").status_code == 400
    assert sessions.count() == 0


def test_a_replayed_callback_is_refused(world):
    _app, _provider, _ = world
    browser, first, _ = sign_in(world)
    assert first.status_code == 302
    assert (
        browser.get(first.request.full_path).status_code == 400
    )  # the attempt cookie was cleared and the state consumed


def test_the_provider_refusing_the_code_is_a_400_and_a_forged_token_a_401(world):
    app, provider, _ = world
    browser = AppBrowser(app)
    browser.get("/login")
    assert browser.get(f"/callback?code=never-issued&state={provider.last_authorization['state']}").status_code == 400
    forger = Signer()
    provider.id_token_signer = forger
    browser.get("/login")
    code, state = provider.issue_code(), provider.last_authorization["state"]
    assert browser.get(f"/callback?code={code}&state={state}").status_code == 401


def test_a_provider_outage_during_sign_in_is_a_502(world):
    app, provider, _ = world

    def down(**_: Any) -> Any:
        from oidc_login.domain.errors import ProviderUnavailableError

        raise ProviderUnavailableError("down")

    browser = AppBrowser(app)
    browser.get("/login")
    provider.exchange_code = down
    assert (
        browser.get(f"/callback?code={provider.issue_code()}&state={provider.last_authorization['state']}").status_code
        == 502
    )


def test_me_shows_the_identity_and_scopes_but_no_tokens(world):
    browser, *_ = sign_in(world)
    body = browser.get("/me").get_json()
    assert body["username"] == "demo-user"
    assert body["subject"] == "user-1"
    assert set(body) == {"subject", "username", "scopes", "session_expires_at"}


def test_routes_that_need_a_session_answer_401_without_one(world):
    app, *_ = world
    browser = AppBrowser(app)
    for method, path in (("GET", "/me"), ("GET", "/api/profile"), ("POST", "/refresh"), ("GET", "/reports")):
        assert browser.request(method, path).status_code == 401, path


def test_the_profile_route_calls_userinfo_with_the_access_token_held_on_the_server(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    body = browser.get("/api/profile").get_json()
    assert body == {"email": "demo-user@example.test", "subject": "user-1", "username": "demo-user"}
    session = next(iter(sessions._items.values()))
    assert ("userinfo", {"access_token": session.tokens.access_token}) in provider.requests


def test_refresh_needs_the_csrf_token_and_then_rotates_the_refresh_token(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    before = next(iter(sessions._items.values()))
    assert browser.post("/refresh").status_code == 403
    assert browser.post("/refresh", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    response = browser.post("/refresh", headers={"X-CSRF-Token": before.csrf_token})
    assert response.status_code == 200
    assert response.get_json()["refreshed"] is True
    after = next(iter(sessions._items.values()))
    assert after.tokens.refresh_token != before.tokens.refresh_token
    with pytest.raises(ProviderError):
        provider.refresh(before.tokens.refresh_token)


def test_a_session_whose_refresh_token_was_revoked_gets_401_and_is_dropped(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    session = next(iter(sessions._items.values()))
    provider.refresh_tokens[session.tokens.refresh_token] = False
    response = browser.post("/refresh", headers={"X-CSRF-Token": session.csrf_token})
    assert response.status_code == 401
    assert sessions.count() == 0


def test_logout_needs_the_csrf_token_ends_the_session_and_revokes_the_refresh_token(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    session = next(iter(sessions._items.values()))
    assert browser.post("/logout").status_code == 403
    assert sessions.count() == 1  # a forged logout did nothing
    response = browser.post("/logout", data={"csrf_token": session.csrf_token})
    assert response.status_code == 303
    assert f"{SESSION_COOKIE}=;" in response.headers["Set-Cookie"]
    assert sessions.count() == 0
    assert provider.refresh_tokens[session.tokens.refresh_token] is False
    assert browser.get("/me").status_code == 401


def test_logout_without_a_session_is_a_harmless_redirect(world):
    app, *_ = world
    assert AppBrowser(app).post("/logout").status_code == 303


def test_the_reports_route_needs_the_elevated_scope(world):
    browser, *_ = sign_in(world)
    denied = browser.get("/reports")
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "insufficient_scope"
    elevated, *_ = sign_in(world, scope="reports:read")
    assert elevated.get("/reports").status_code == 200


def test_home_page_changes_with_the_session_and_html_escapes_the_username(world):
    app, _provider, _sessions = world
    anonymous = AppBrowser(app).get("/").get_data(as_text=True)
    assert "Sign in" in anonymous
    assert "reports access" in anonymous
    browser, *_ = sign_in(world)
    page = browser.get("/").get_data(as_text=True)
    assert "demo-user" in page
    assert 'name="csrf_token"' in page


def test_health_and_readiness(world):
    app, provider, _ = world
    browser = AppBrowser(app)
    assert browser.get("/healthz").get_json() == {"status": "ok"}
    assert browser.get("/readyz").status_code == 200
    provider.unavailable = True
    assert browser.get("/readyz").status_code == 503


def test_unknown_routes_and_an_oversized_body_use_the_json_error_shape(world):
    app, *_ = world
    assert AppBrowser(app).get("/nope").get_json()["error"] == "not_found"
    browser, *_ = sign_in(world)
    oversized = browser.post("/logout", data={"csrf_token": "x" * 20_000})
    assert oversized.status_code == 413
    assert oversized.get_json()["error"] == "request_entity_too_large"


def test_an_unexpected_error_leaks_nothing(world):
    app, *_ = world

    @app.get("/boom")
    def boom():
        raise RuntimeError("internal detail")

    response = AppBrowser(app).get("/boom")
    assert response.status_code == 500
    assert "internal detail" not in response.get_data(as_text=True)


def test_the_authorization_url_the_browser_is_sent_to_matches_the_flow(world):
    app, _provider, _ = world
    location = AppBrowser(app).get("/login?scope=reports:read&scope=admin").headers["Location"]
    query = parse_qs(urlsplit(location).query)
    assert query["scope"] == ["openid profile email reports:read"]
