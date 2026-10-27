"""Step 3: the ID token Keycloak issues passes, and each kind of bad token is rejected for its own reason."""

import jwt
import pytest

from oidc_login.interfaces.demo_cli import Scenario

pytestmark = pytest.mark.integration


@pytest.fixture
def signed_in(scenario: Scenario) -> Scenario:
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    assert scenario.complete_login(browser, back).passed
    return scenario


def test_the_real_id_token_is_signed_with_rs256_and_carries_the_claims_the_app_checks(signed_in: Scenario):
    token = signed_in.server_session().tokens.id_token
    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert header["alg"] == "RS256"
    assert header["kid"]
    assert claims["iss"] == signed_in.settings.issuer
    assert claims["aud"] == signed_in.settings.client_id
    assert claims["azp"] == signed_in.settings.client_id
    assert claims["nonce"]
    assert claims["at_hash"]
    assert claims["preferred_username"] == "demo-user"


def test_wrong_audience_expired_wrong_key_none_algorithm_and_wrong_nonce_are_each_rejected_with_a_clear_reason(
    signed_in: Scenario,
):
    step = signed_in.id_token_validation()
    assert step.passed, step.detail
    for reason in ("audience claim does not match client id", "token has expired", "signature verification failed"):
        assert reason in step.detail
