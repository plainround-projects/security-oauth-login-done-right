"""Step 2: the authorization code flow with PKCE, with the token exchange on the server."""

import httpx
import pytest

from oidc_login.interfaces.demo_cli import Scenario

pytestmark = pytest.mark.integration


def test_the_authorization_request_carries_state_nonce_and_an_s256_challenge_and_no_secret(scenario: Scenario):
    step, _ = scenario.start_login(scenario.new_browser())
    assert step.passed, step.detail


def test_the_user_authenticates_at_the_provider_and_comes_back_to_the_registered_uri(scenario: Scenario):
    _, location = scenario.start_login(scenario.new_browser())
    step, back = scenario.authenticate(location)
    assert step.passed, step.detail
    assert back.startswith(scenario.settings.redirect_uri)
    assert "access_token" not in back
    assert "id_token" not in back


def test_a_full_sign_in_works_and_the_browser_receives_only_an_opaque_cookie(scenario: Scenario):
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    step = scenario.complete_login(browser, back)
    assert step.passed, step.detail


def test_the_token_exchange_is_one_server_to_server_post_with_the_verifier_and_the_secret(scenario: Scenario):
    seen: list[httpx.Request] = []
    scenario.container.provider._http.event_hooks["request"].append(seen.append)
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    scenario.complete_login(browser, back)
    exchanges = [r for r in seen if r.method == "POST" and r.url.path.endswith("/token")]
    assert len(exchanges) == 1
    body = exchanges[0].content.decode()
    assert "grant_type=authorization_code" in body
    assert "code_verifier=" in body
    assert "client_secret=" in body
    assert str(exchanges[0].url).startswith(scenario.settings.issuer)  # the app called the provider directly
