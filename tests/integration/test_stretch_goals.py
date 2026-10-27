"""Stretch goals: an elevated scope on one route, and a public client that must use PKCE."""

import pytest

from oidc_login.interfaces.demo_cli import Scenario

pytestmark = pytest.mark.integration


def test_a_route_needing_the_reports_scope_refuses_a_sign_in_that_did_not_ask_for_it(scenario: Scenario):
    step = scenario.scope_check()
    assert step.passed, step.detail
    assert "403" in step.detail
    assert "200" in step.detail


def test_a_public_client_cannot_exchange_a_code_without_the_pkce_verifier(scenario: Scenario):
    step = scenario.public_client_needs_pkce()
    assert step.passed, step.detail
