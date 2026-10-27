"""Steps 5 and 6: the session, refresh with rotation, and sign-out with revocation."""

import pytest

from oidc_login.interfaces.demo_cli import Scenario
from oidc_login.interfaces.http.security import SESSION_COOKIE

pytestmark = pytest.mark.integration


@pytest.fixture
def signed_in(scenario: Scenario):
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    assert scenario.complete_login(browser, back).passed
    return scenario, browser


def test_the_session_shows_an_identity_and_no_token_and_the_server_uses_the_access_token_for_the_browser(signed_in):
    scenario, browser = signed_in
    step = scenario.session_facts(browser)
    assert step.passed, step.detail
    assert browser.cookie(SESSION_COOKIE) is not None
    assert "." not in (browser.cookie(SESSION_COOKIE) or "")  # not a JWT


def test_a_refresh_issues_a_new_refresh_token_and_the_old_one_is_refused_by_the_provider(signed_in):
    scenario, browser = signed_in
    step = scenario.refresh_rotation(browser)
    assert step.passed, step.detail
    assert "invalid_grant" in step.detail


def test_the_session_survives_a_refresh_and_keeps_its_identity(signed_in):
    scenario, browser = signed_in
    scenario.refresh_rotation(browser)
    assert browser.get("/me").get_json()["username"] == "demo-user"


def test_after_sign_out_the_old_session_and_the_old_refresh_token_are_both_refused(signed_in):
    scenario, browser = signed_in
    step = scenario.logout(browser)
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0


def test_a_refresh_token_the_provider_has_revoked_ends_the_session_on_the_next_use(signed_in):
    scenario, browser = signed_in
    session = scenario.server_session()
    scenario.container.provider.revoke(session.tokens.refresh_token or "")
    response = browser.post("/refresh", headers={"X-CSRF-Token": session.csrf_token})
    assert response.status_code == 401
    assert scenario.container.sessions.count() == 0
