"""``oidc-login-demo``: the lesson's scenario against the running provider, printed as checked steps.

The app runs in-process (the same Flask app and the same adapters as in production, over the Flask test client) so the
demo can show what only the server sees: the tokens it holds, the refresh token before and after rotation. The users
are scripted browsers; passwords come from the environment and are never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from oidc_login.domain.claims import Expectations, check_id_token_claims
from oidc_login.domain.errors import LoginError, ProviderError, TokenValidationError
from oidc_login.domain.models import UserSession
from oidc_login.domain.pkce import challenge_for
from oidc_login.infrastructure.clock import SystemClock
from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier
from oidc_login.infrastructure.settings import Settings
from oidc_login.interfaces.composition import Container, build_container
from oidc_login.interfaces.http.app import create_app
from oidc_login.interfaces.http.security import LOGIN_COOKIE, SESSION_COOKIE
from oidc_login.interfaces.scripted_browser import AppBrowser, ProviderBrowser

DEMO_USERNAME = "demo-user"
SPA_CLIENT_ID = "notes-spa"
SPA_REDIRECT_URI = "http://localhost:3001/callback"


@dataclass(frozen=True, slots=True)
class Step:
    """One checked claim of the scenario."""

    name: str
    passed: bool
    detail: str


def _step(name: str, passed: bool, detail: str) -> Step:
    return Step(name, passed, detail)


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _cookie_attributes(set_cookie_headers: list[str], name: str) -> tuple[str, str]:
    cookie = next((header for header in set_cookie_headers if header.startswith(f"{name}=")), "")
    value = cookie.split("=", 1)[1].split(";", 1)[0] if cookie else ""
    return value, "; ".join(part.strip() for part in cookie.split(";")[1:])


class Scenario:
    """The scenario's moving parts and one method per claim. Each method returns a ``Step`` and never raises on a
    failed expectation; the tests call the same methods and assert on the result."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self.settings = Settings.from_environment(env)
        self.container: Container = build_container(self.settings)
        self.app = create_app(self.container)
        self.password = env.get("DEMO_USER_PASSWORD", "")
        self.user = ProviderBrowser(DEMO_USERNAME, self.password)

    def close(self) -> None:
        """Release the HTTP clients."""
        self.user.close()
        self.container.provider.close()

    # -- helpers ---------------------------------------------------------------------------------------------

    def server_session(self) -> UserSession:
        """The session the server created most recently (the demo signs in one browser at a time)."""
        sessions = list(self.container.sessions._items.values())
        if not sessions:
            raise RuntimeError("the server holds no session")
        return max(sessions, key=lambda session: session.created_at)

    def new_browser(self) -> AppBrowser:
        """A fresh browser with no cookies."""
        return AppBrowser(self.app)

    def authorize_code(self, *, client_id: str, redirect_uri: str, verifier: str) -> str:
        """Get an authorization code for any client from the provider, the way a browser would."""
        url = self.container.provider.authorization_url(
            state="demo-state", nonce="demo-nonce", code_challenge=challenge_for(verifier), scope="openid"
        )
        url = _replace_query_value(_replace_query_value(url, "client_id", client_id), "redirect_uri", redirect_uri)
        hop = self.user.authorize(url)
        if hop.location is None:
            raise RuntimeError(f"no authorization code: provider answered {hop.status}")
        return _query(hop.location)["code"]

    # -- step 1 ----------------------------------------------------------------------------------------------

    def discovery(self) -> Step:
        """The provider's discovery document and keys are reachable."""
        provider = self.container.provider
        metadata = provider.metadata()
        keys = provider.jwks().get("keys", [])
        usable = isinstance(keys, list) and len(keys) >= 1
        return _step(
            "the provider's discovery document and signing keys are reachable",
            usable and metadata.issuer == self.settings.issuer,
            f"issuer {metadata.issuer}; {len(keys)} signing keys at {metadata.jwks_uri}",
        )

    # -- steps 2 to 4 ----------------------------------------------------------------------------------------

    def start_login(self, browser: AppBrowser, scope: str | None = None) -> tuple[Step, str]:
        """The app sends the browser to the provider with state, nonce and an S256 challenge."""
        response = browser.get("/login" + (f"?scope={scope}" if scope else ""))
        location = response.headers.get("Location", "")
        query = _query(location)
        value, attributes = _cookie_attributes(response.headers.getlist("Set-Cookie"), LOGIN_COOKIE)
        checks = {
            "response_type=code": query.get("response_type") == "code",
            "S256 challenge": query.get("code_challenge_method") == "S256"
            and len(query.get("code_challenge", "")) == 43,
            "state": len(query.get("state", "")) >= 32,
            "nonce": len(query.get("nonce", "")) >= 32,
            "exact redirect_uri": query.get("redirect_uri") == self.settings.redirect_uri,
            "no client secret in the URL": self.settings.client_secret not in location and "client_secret" not in query,
            "no verifier in the URL": "code_verifier" not in query,
            "attempt cookie HttpOnly Secure SameSite=Lax": all(
                a in attributes for a in ("HttpOnly", "Secure", "SameSite=Lax")
            )
            and bool(value),
        }
        missing = [name for name, ok in checks.items() if not ok]
        detail = f"redirect to {urlsplit(location).path}: " + ", ".join(checks) if not missing else f"failed: {missing}"
        return _step(
            "the app sends the browser to the provider with state, nonce and an S256 challenge", not missing, detail
        ), location

    def authenticate(self, location: str) -> tuple[Step, str]:
        """The user signs in at the provider; it redirects to the registered URI with a code and the same state."""
        hop = self.user.authorize(location)
        back = hop.location or ""
        ok = back.startswith(self.settings.redirect_uri + "?") and {"code", "state"} <= set(_query(back))
        same_state = _query(back).get("state") == _query(location).get("state")
        return (
            _step(
                "the user authenticates at the provider and is redirected to the one registered URI",
                ok and same_state,
                f"provider answered {hop.status}, redirect to {urlsplit(back).path} with code and the same state",
            ),
            back,
        )

    def complete_login(self, browser: AppBrowser, callback_location: str) -> Step:
        """The callback exchanges the code on the server and starts an opaque session."""
        response = browser.follow_callback(callback_location)
        value, attributes = _cookie_attributes(response.headers.getlist("Set-Cookie"), SESSION_COOKIE)
        if not self.container.sessions.count():
            return _step(
                "the code is exchanged on the server and the browser gets only an opaque session cookie",
                False,
                f"callback -> {response.status_code}: no session was created",
            )
        session = self.server_session()
        held = [session.tokens.access_token, session.tokens.refresh_token or "", session.tokens.id_token]
        pages = [response, browser.get("/"), browser.get("/me")]
        blob = "".join(page.get_data(as_text=True) + str(dict(page.headers)) for page in pages) + callback_location
        leaked = [index for index, token in enumerate(held) if token and token in blob]
        ok = (
            response.status_code == 302
            and all(a in attributes for a in ("HttpOnly", "Secure", "SameSite=Lax"))
            and value.count(".") == 0
            and len(value) >= 40
            and not leaked
        )
        detail = (
            f"callback -> {response.status_code}; cookie {SESSION_COOKIE}=<{len(value)} opaque characters> "
            f"({attributes}); "
            f"server holds access, refresh and ID tokens; none appears in a URL, header or page"
        )
        return _step(
            "the code is exchanged on the server and the browser gets only an opaque session cookie", ok, detail
        )

    # -- step 3 ----------------------------------------------------------------------------------------------

    def id_token_validation(self) -> Step:
        """The validator rejects a wrong audience, an expired token, a wrong key, algorithm none and a wrong nonce."""
        session = self.server_session()
        token = session.tokens.id_token
        provider = self.container.provider
        verifier = JwksTokenVerifier(provider.jwks)
        claims = verifier.verify(token)
        now = SystemClock().now()
        good = Expectations(self.settings.issuer, self.settings.client_id, str(claims.get("nonce")), now)
        check_id_token_claims(claims, good)  # the real token passes
        header = jwt.get_unverified_header(token)

        forger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(claims, forger, algorithm="RS256", headers={"kid": header["kid"]})
        unsigned = jwt.encode(claims, key="", algorithm="none", headers={"kid": header["kid"]})
        outcomes: list[tuple[str, str]] = []

        def attempt(label: str, action: Callable[[], object]) -> None:
            try:
                action()
            except TokenValidationError as error:
                outcomes.append((label, error.reason))
            else:
                outcomes.append((label, "ACCEPTED"))

        attempt("wrong audience", lambda: check_id_token_claims(claims, replace(good, client_id="some-other-client")))
        attempt("expired", lambda: check_id_token_claims(claims, replace(good, now=now + timedelta(days=1))))
        attempt("wrong key", lambda: verifier.verify(forged))
        attempt("none algorithm", lambda: verifier.verify(unsigned))
        attempt("wrong nonce", lambda: check_id_token_claims(claims, replace(good, nonce="another-logins-nonce")))
        expected = {
            "wrong audience": "audience claim does not match client id",
            "expired": "token has expired",
            "wrong key": "signature verification failed",
            "none algorithm": "signing algorithm 'none' is not accepted",
            "wrong nonce": "nonce mismatch: possible token substitution",
        }
        ok = dict(outcomes) == expected
        return _step(
            "the ID token validator rejects five bad tokens, each for its own reason",
            ok,
            "; ".join(f"{k} -> {v}" for k, v in outcomes),
        )

    # -- step 4 ----------------------------------------------------------------------------------------------

    def mismatched_state(self) -> Step:
        """A callback whose state is not the one this browser's login sent is refused."""
        browser = self.new_browser()
        _, location = self.start_login(browser)
        _, back = self.authenticate(location)
        tampered = back.replace(f"state={_query(back)['state']}", "state=attacker-chosen-state")
        status = browser.follow_callback(tampered).status_code
        return _step(
            "a callback with a mismatched state is refused",
            status == 400 and browser.cookie(SESSION_COOKIE) is None,
            f"GET /callback with a changed state -> {status}",
        )

    def login_csrf(self) -> Step:
        """A callback from a browser that did not start the login is refused (login CSRF)."""
        attacker, victim = self.new_browser(), self.new_browser()
        _, location = self.start_login(attacker)
        _, back = self.authenticate(location)
        status = victim.follow_callback(
            back
        ).status_code  # the attacker's valid code and state, in the victim's browser
        return _step(
            "a callback from a browser that did not start the login is refused",
            status == 400 and victim.cookie(SESSION_COOKIE) is None,
            f"the attacker's own code and state in another browser -> {status}",
        )

    def replayed_callback(self) -> Step:
        """A callback that already succeeded cannot be replayed."""
        browser = self.new_browser()
        _, location = self.start_login(browser)
        _, back = self.authenticate(location)
        first = browser.follow_callback(back).status_code
        again = browser.follow_callback(back).status_code
        return _step(
            "a callback cannot be replayed", first == 302 and again == 400, f"first use -> {first}, replay -> {again}"
        )

    def lookalike_redirect_uri(self) -> Step:
        """The provider refuses a redirect URI that is not exactly the registered one, before the app sees anything."""
        browser = self.new_browser()
        _, location = self.start_login(browser)
        lookalikes = [
            self.settings.redirect_uri + ".evil.example.test",
            self.settings.redirect_uri + "/",
            self.settings.redirect_uri.replace("localhost", "localhost.evil.example.test"),
        ]
        results = []
        for lookalike in lookalikes:
            hop = self.user.authorize(_replace_query_value(location, "redirect_uri", lookalike))
            results.append((lookalike.removeprefix("http://"), hop.status, hop.location is None))
        ok = all(status == 400 and refused for _, status, refused in results)
        return _step(
            "a lookalike redirect URI is refused by the provider itself",
            ok,
            "; ".join(f"{uri} -> {status}, no redirect" for uri, status, _ in results),
        )

    def code_reuse(self) -> Step:
        """An authorization code can be exchanged once; the second exchange is refused by the provider."""
        verifier = self.container.flow._tokens.token(64)
        code = self.authorize_code(
            client_id=self.settings.client_id, redirect_uri=self.settings.redirect_uri, verifier=verifier
        )
        provider = self.container.provider
        provider.exchange_code(code=code, code_verifier=verifier)
        try:
            provider.exchange_code(code=code, code_verifier=verifier)
        except ProviderError as error:
            return _step(
                "a code cannot be exchanged a second time",
                error.code == "invalid_grant",
                f"second exchange: {error.code} ({error.description})",
            )
        return _step("a code cannot be exchanged a second time", False, "the second exchange was accepted")

    def wrong_pkce_verifier(self) -> Step:
        """Without the right PKCE verifier a stolen code is useless."""
        verifier = self.container.flow._tokens.token(64)
        code = self.authorize_code(
            client_id=self.settings.client_id, redirect_uri=self.settings.redirect_uri, verifier=verifier
        )
        try:
            self.container.provider.exchange_code(code=code, code_verifier="w" * 64)
        except ProviderError as error:
            return _step(
                "a stolen code is useless without the PKCE verifier",
                error.code == "invalid_grant",
                f"exchange with another verifier: {error.code} ({error.description})",
            )
        return _step("a stolen code is useless without the PKCE verifier", False, "the exchange was accepted")

    # -- step 5 and 6 ----------------------------------------------------------------------------------------

    def session_facts(self, browser: AppBrowser) -> Step:
        """The session answers with an identity and no tokens, and the server can use its access token."""
        me = browser.get("/me").get_json()
        profile = browser.get("/api/profile")
        ok = (
            me is not None
            and set(me) == {"subject", "username", "scopes", "session_expires_at"}
            and profile.status_code == 200
        )
        return _step(
            "the session shows who signed in, never a token, and the server calls the provider for the browser",
            ok,
            f"/me -> {sorted(me or {})}; /api/profile -> {profile.status_code} {profile.get_json()}",
        )

    def refresh_rotation(self, browser: AppBrowser) -> Step:
        """A refresh issues a new refresh token and the provider refuses the old one."""
        before = self.server_session()
        old = before.tokens.refresh_token or ""
        response = browser.post("/refresh", headers={"X-CSRF-Token": before.csrf_token})
        after = self.server_session()
        new = after.tokens.refresh_token or ""
        try:
            self.container.provider.refresh(old)
            reuse = "ACCEPTED"
        except ProviderError as error:
            reuse = error.code
        ok = response.status_code == 200 and new != old and reuse == "invalid_grant"
        return _step(
            "a refresh rotates the refresh token and the old one is refused",
            ok,
            f"POST /refresh -> {response.status_code}; refresh token changed: {new != old}; "
            f"old token at the provider: {reuse}",
        )

    def logout(self, browser: AppBrowser) -> Step:
        """Sign-out ends the session here and revokes the refresh token at the provider."""
        session = self.server_session()
        refresh_token = session.tokens.refresh_token or ""
        old_cookie = browser.cookie(SESSION_COOKIE)
        response = browser.post("/logout", data={"csrf_token": session.csrf_token})
        replay = self.new_browser()
        replay.client.set_cookie(SESSION_COOKIE, old_cookie or "", domain="localhost")
        after = replay.get("/me").status_code
        try:
            self.container.provider.refresh(refresh_token)
            revoked = "ACCEPTED"
        except LoginError as error:
            revoked = error.code if isinstance(error, ProviderError) else type(error).__name__
        ok = (
            response.status_code == 303
            and after == 401
            and revoked == "invalid_grant"
            and self.container.sessions.count() == 0
        )
        return _step(
            "after sign-out the old session and the old refresh token are both refused",
            ok,
            f"POST /logout -> {response.status_code}; old cookie -> {after}; refresh token at the provider: {revoked}",
        )

    # -- stretch goals ---------------------------------------------------------------------------------------

    def scope_check(self) -> Step:
        """A route that needs an elevated scope refuses a sign-in that did not ask for it."""
        plain = self.new_browser()
        _, location = self.start_login(plain)
        _, back = self.authenticate(location)
        plain.follow_callback(back)
        denied = plain.get("/reports").status_code
        plain.post("/logout", data={"csrf_token": self.server_session().csrf_token})
        elevated = self.new_browser()
        _, location = self.start_login(elevated, scope="reports:read")
        _, back = self.authenticate(location)
        elevated.follow_callback(back)
        allowed = elevated.get("/reports").status_code
        elevated.post("/logout", data={"csrf_token": self.server_session().csrf_token})
        return _step(
            "a route that needs the reports:read scope refuses a sign-in without it",
            (denied, allowed) == (403, 200),
            f"/reports without the scope -> {denied}, with it -> {allowed}",
        )

    def public_client_needs_pkce(self) -> Step:
        """The public client has no secret, so the provider refuses its code exchange without a verifier."""
        verifier = self.container.flow._tokens.token(64)
        code = self.authorize_code(client_id=SPA_CLIENT_ID, redirect_uri=SPA_REDIRECT_URI, verifier=verifier)
        endpoint = self.container.provider.metadata().token_endpoint
        data = {
            "grant_type": "authorization_code",
            "client_id": SPA_CLIENT_ID,
            "code": code,
            "redirect_uri": SPA_REDIRECT_URI,
        }
        without = httpx.post(endpoint, data=data, timeout=30)
        code2 = self.authorize_code(client_id=SPA_CLIENT_ID, redirect_uri=SPA_REDIRECT_URI, verifier=verifier)
        with_verifier = httpx.post(endpoint, data={**data, "code": code2, "code_verifier": verifier}, timeout=30)
        ok = without.status_code == 400 and with_verifier.status_code == 200
        reason = without.json().get("error_description", without.json().get("error", ""))
        return _step(
            "a public client (no secret) cannot exchange a code without the PKCE verifier",
            ok,
            f"without a verifier -> {without.status_code} ({reason}); with it -> {with_verifier.status_code}",
        )


def _replace_query_value(url: str, name: str, value: str) -> str:
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    query[name] = value
    return parts._replace(query=urlencode(query)).geturl()


def run_scenario(env: Mapping[str, str]) -> list[Step]:
    """Run every step in order against the provider named by ``env`` and return the results."""
    scenario = Scenario(env)
    steps: list[Step] = []
    try:
        steps.append(scenario.discovery())
        browser = scenario.new_browser()
        started, location = scenario.start_login(browser)
        steps.append(started)
        authenticated, back = scenario.authenticate(location)
        steps.append(authenticated)
        steps.append(scenario.complete_login(browser, back))
        steps.append(scenario.id_token_validation())
        steps.append(scenario.session_facts(browser))
        steps.append(scenario.refresh_rotation(browser))
        steps.append(scenario.logout(browser))
        steps.extend(
            [
                scenario.mismatched_state(),
                scenario.login_csrf(),
                scenario.replayed_callback(),
                scenario.lookalike_redirect_uri(),
                scenario.code_reuse(),
                scenario.wrong_pkce_verifier(),
                scenario.scope_check(),
                scenario.public_client_needs_pkce(),
            ]
        )
    finally:
        scenario.close()
    return steps


def main(argv: list[str] | None = None, *, out: Callable[[str], None] = print) -> int:
    """Run the scenario and print one line per step; exit 1 when a step fails."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    steps = run_scenario(os.environ)
    for number, step in enumerate(steps, start=1):
        out(f"{number:>2}. {'PASS' if step.passed else 'FAIL'}  {step.name}\n        {step.detail}")
    failed = [step for step in steps if not step.passed]
    out(f"{len(steps) - len(failed)} of {len(steps)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
