"""Step 1: the provider is running, discoverable, and the app is registered with one exact redirect URI."""

import os

import httpx
import pytest

from oidc_login.interfaces.demo_cli import Scenario

pytestmark = pytest.mark.integration


def _admin_token(base: str) -> str:
    response = httpx.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.environ.get("KEYCLOAK_ADMIN", "admin"),
            "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        },
        timeout=60,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def test_the_discovery_document_and_the_signing_keys_are_reachable(scenario: Scenario):
    step = scenario.discovery()
    assert step.passed, step.detail
    metadata = scenario.container.provider.metadata()
    assert metadata.issuer == scenario.settings.issuer
    assert metadata.revocation_endpoint.endswith("/revoke")


def test_the_provider_publishes_exactly_one_rs256_signing_key(scenario: Scenario):
    keys = [key for key in scenario.container.provider.jwks()["keys"] if key.get("use") == "sig"]
    assert [key["alg"] for key in keys] == ["RS256"]


def test_the_app_is_registered_as_a_confidential_client_with_one_exact_redirect_uri(scenario: Scenario):
    base = scenario.settings.issuer.split("/realms/")[0]
    token = _admin_token(base)
    clients = httpx.get(
        f"{base}/admin/realms/demo/clients",
        params={"clientId": scenario.settings.client_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    ).json()
    assert len(clients) == 1
    registration = clients[0]
    assert registration["redirectUris"] == [scenario.settings.redirect_uri]  # one entry, no wildcard, no second URI
    assert registration["publicClient"] is False
    assert registration["standardFlowEnabled"] is True
    assert registration["implicitFlowEnabled"] is False
    assert registration["directAccessGrantsEnabled"] is False  # no password grant: the app never sees the password
    assert registration["attributes"]["pkce.code.challenge.method"] == "S256"
    assert registration["webOrigins"] == []
