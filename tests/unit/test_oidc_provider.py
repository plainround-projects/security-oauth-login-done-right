import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from oidc_login.domain.errors import ProviderError, ProviderUnavailableError
from oidc_login.infrastructure.oidc_provider import OidcProvider
from tests.fakes import CLIENT_ID, ISSUER, REDIRECT_URI

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    "userinfo_endpoint": f"{ISSUER}/protocol/openid-connect/userinfo",
    "revocation_endpoint": f"{ISSUER}/protocol/openid-connect/revoke",
}
TOKEN_BODY = {"access_token": "a", "refresh_token": "r", "id_token": "i", "expires_in": 120, "scope": "openid profile"}


def provider_with(handler, sleeps=None):
    transport = httpx.MockTransport(handler)
    return OidcProvider(
        issuer=ISSUER,
        discovery_base=ISSUER,
        client_id=CLIENT_ID,
        client_secret="the-secret",
        redirect_uri=REDIRECT_URI,
        http=httpx.Client(transport=transport),
        sleep=(sleeps.append if sleeps is not None else (lambda _: None)),
    )


def routes(**overrides):
    table = {
        "/.well-known/openid-configuration": (200, DISCOVERY),
        "/protocol/openid-connect/certs": (200, {"keys": []}),
        "/protocol/openid-connect/token": (200, TOKEN_BODY),
        "/protocol/openid-connect/revoke": (200, {}),
        "/protocol/openid-connect/userinfo": (200, {"sub": "user-1"}),
    }
    table.update(overrides)
    seen = []

    def handler(request):
        path = request.url.path.removeprefix("/realms/demo")
        seen.append(request)
        status, body = table[path]
        return httpx.Response(status, json=body)

    return handler, seen


def test_the_discovery_document_is_fetched_once_and_cached():
    handler, seen = routes()
    provider = provider_with(handler)
    assert provider.metadata().token_endpoint.endswith("/token")
    provider.metadata()
    assert len(seen) == 1


def test_a_discovery_document_for_another_issuer_is_refused():
    handler, _ = routes(
        **{"/.well-known/openid-configuration": (200, {**DISCOVERY, "issuer": "http://evil.example.test/realms/demo"})}
    )
    with pytest.raises(ProviderUnavailableError, match="does not match OIDC_ISSUER"):
        provider_with(handler).metadata()


def test_a_discovery_document_missing_an_endpoint_is_refused():
    handler, _ = routes(
        **{"/.well-known/openid-configuration": (200, {k: v for k, v in DISCOVERY.items() if k != "jwks_uri"})}
    )
    with pytest.raises(ProviderUnavailableError, match="jwks_uri"):
        provider_with(handler).metadata()


def test_gets_are_retried_with_backoff_and_then_succeed():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=DISCOVERY)

    sleeps: list[float] = []
    assert provider_with(handler, sleeps).metadata().issuer == ISSUER
    assert len(attempts) == 3
    assert sleeps == [0.2, 0.5]


def test_gets_give_up_after_the_last_retry_with_a_clear_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailableError, match="could not fetch"):
        provider_with(handler).metadata()


def test_a_client_error_on_a_get_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(ProviderUnavailableError, match="404"):
        provider_with(handler).metadata()
    assert len(calls) == 1


def test_the_authorization_url_asks_for_the_code_flow_with_s256_and_the_one_redirect_uri():
    handler, _ = routes()
    url = provider_with(handler).authorization_url(
        state="s", nonce="n", code_challenge="c", scope="openid reports:read"
    )
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert parts.path.endswith("/protocol/openid-connect/auth")
    assert query == {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "openid reports:read",
        "state": "s",
        "nonce": "n",
        "code_challenge": "c",
        "code_challenge_method": "S256",
    }
    assert "the-secret" not in url  # the client secret never goes through the browser


def test_the_code_exchange_is_a_server_to_server_post_with_the_verifier_and_the_secret_in_the_body():
    handler, seen = routes()
    response = provider_with(handler).exchange_code(code="the-code", code_verifier="v" * 64)
    request = seen[-1]
    form = parse_qs(request.content.decode())
    assert request.method == "POST"
    assert request.url.path.endswith("/token")
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["the-code"]
    assert form["code_verifier"] == ["v" * 64]
    assert form["client_secret"] == ["the-secret"]
    assert form["redirect_uri"] == [REDIRECT_URI]
    assert (response.access_token, response.refresh_token, response.id_token, response.expires_in) == (
        "a",
        "r",
        "i",
        120,
    )


def test_the_providers_error_code_is_carried_in_the_exception_and_the_post_is_not_retried():
    handler, seen = routes(
        **{"/protocol/openid-connect/token": (400, {"error": "invalid_grant", "error_description": "Code not valid"})}
    )
    with pytest.raises(ProviderError) as refused:
        provider_with(handler).exchange_code(code="used", code_verifier="v" * 64)
    assert refused.value.code == "invalid_grant"
    assert refused.value.description == "Code not valid"
    assert sum(request.method == "POST" for request in seen) == 1


def test_an_error_body_that_is_not_json_still_yields_a_provider_error():
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(502, text="<html>bad gateway</html>")
            if request.method == "POST"
            else httpx.Response(200, json=DISCOVERY)
        )
    )
    provider = OidcProvider(
        issuer=ISSUER,
        discovery_base=ISSUER,
        client_id=CLIENT_ID,
        client_secret="s",
        redirect_uri=REDIRECT_URI,
        http=httpx.Client(transport=transport),
    )
    with pytest.raises(ProviderError) as refused:
        provider.refresh("r")
    assert refused.value.code == "http_502"


def test_a_token_response_missing_fields_is_an_invalid_response():
    handler, _ = routes(**{"/protocol/openid-connect/token": (200, {"access_token": "a"})})
    with pytest.raises(ProviderError) as refused:
        provider_with(handler).refresh("r")
    assert refused.value.code == "invalid_response"


def test_a_network_failure_on_a_post_is_provider_unavailable():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=DISCOVERY)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ProviderUnavailableError, match="ReadTimeout"):
        provider_with(handler).refresh("r")


def test_refresh_and_revoke_send_the_expected_forms():
    handler, seen = routes()
    provider = provider_with(handler)
    provider.refresh("old-refresh")
    provider.revoke("old-refresh")
    refresh_form, revoke_form = (parse_qs(request.content.decode()) for request in seen[-2:])
    assert refresh_form["grant_type"] == ["refresh_token"]
    assert refresh_form["refresh_token"] == ["old-refresh"]
    assert revoke_form["token"] == ["old-refresh"]
    assert revoke_form["token_type_hint"] == ["refresh_token"]


def test_a_failed_revocation_raises_the_providers_error():
    handler, _ = routes(**{"/protocol/openid-connect/revoke": (400, {"error": "unauthorized_client"})})
    with pytest.raises(ProviderError, match="unauthorized_client"):
        provider_with(handler).revoke("r")


def test_userinfo_sends_the_bearer_token_and_returns_the_claims():
    handler, seen = routes()
    assert provider_with(handler).userinfo("the-access-token") == {"sub": "user-1"}
    assert seen[-1].headers["authorization"] == "Bearer the-access-token"


def test_userinfo_errors_are_mapped():
    handler, _ = routes(**{"/protocol/openid-connect/userinfo": (401, {"error": "invalid_token"})})
    with pytest.raises(ProviderError, match="invalid_token"):
        provider_with(handler).userinfo("expired")

    def down(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=DISCOVERY)
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailableError):
        provider_with(down).userinfo("x")


def test_jwks_are_fetched_from_the_discovered_uri_and_the_client_can_be_closed():
    handler, seen = routes(**{"/protocol/openid-connect/certs": (200, {"keys": [{"kid": "k"}]})})
    provider = provider_with(handler)
    assert provider.jwks() == {"keys": [{"kid": "k"}]}
    assert json.loads(json.dumps(DISCOVERY))["jwks_uri"].endswith("/certs")
    assert len(seen) == 2
    provider.close()
