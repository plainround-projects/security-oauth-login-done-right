"""Step 4: the protections the standard warns about, each shown by what is refused."""

import pytest

from oidc_login.interfaces.demo_cli import Scenario

pytestmark = pytest.mark.integration


def test_a_callback_with_a_mismatched_state_is_refused(scenario: Scenario):
    step = scenario.mismatched_state()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0


def test_a_valid_callback_in_a_browser_that_did_not_start_the_login_is_refused(scenario: Scenario):
    step = scenario.login_csrf()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0


def test_a_successful_callback_cannot_be_replayed(scenario: Scenario):
    step = scenario.replayed_callback()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 1  # the first use created the only session


def test_the_provider_refuses_lookalike_redirect_uris_before_the_app_sees_anything(scenario: Scenario):
    step = scenario.lookalike_redirect_uri()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0


def test_a_code_can_be_exchanged_only_once(scenario: Scenario):
    step = scenario.code_reuse()
    assert step.passed, step.detail
    assert "invalid_grant" in step.detail


def test_a_code_is_useless_without_the_pkce_verifier(scenario: Scenario):
    step = scenario.wrong_pkce_verifier()
    assert step.passed, step.detail
    assert "invalid_grant" in step.detail
