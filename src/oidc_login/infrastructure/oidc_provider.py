"""The OpenID Connect provider over HTTP: discovery, the authorization URL, and the back-channel calls.

Back-channel POSTs (code exchange, refresh, revoke) are never retried: a second exchange of the same code fails by
design, and a retry would only hide the first error. Idempotent GETs (discovery, keys) retry with backoff.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import httpx

from oidc_login.domain.errors import ProviderError, ProviderUnavailableError
from oidc_login.domain.models import ProviderMetadata, TokenResponse

_log = logging.getLogger("oidc_login.provider")
RETRY_DELAYS = (0.2, 0.5, 1.0)
_REQUIRED = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
    "userinfo_endpoint",
    "revocation_endpoint",
)


class OidcProvider:
    """The ``IdentityProvider`` port over httpx, for a confidential client registered with one redirect URI."""

    def __init__(
        self,
        *,
        issuer: str,
        discovery_base: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        timeout_seconds: float = 10,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._issuer = issuer
        self._discovery_url = f"{discovery_base}/.well-known/openid-configuration"
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=3), follow_redirects=False)
        self._sleep = sleep
        self._metadata: ProviderMetadata | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        """Close the HTTP client (graceful shutdown)."""
        self._http.close()

    def metadata(self) -> ProviderMetadata:
        """The validated discovery document, fetched once and cached."""
        with self._lock:
            if self._metadata is None:
                self._metadata = self._parse_metadata(self._get_json(self._discovery_url))
            return self._metadata

    def jwks(self) -> Mapping[str, Any]:
        """The provider's published signing keys."""
        return self._get_json(self.metadata().jwks_uri)

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str, scope: str) -> str:
        """The authorization request: code flow, S256 challenge, the exact registered redirect URI."""
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri,
                "scope": scope,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.metadata().authorization_endpoint}?{query}"

    def exchange_code(self, *, code: str, code_verifier: str) -> TokenResponse:
        """Server-to-server code exchange; the browser never sees it."""
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": code_verifier,
            }
        )

    def refresh(self, refresh_token: str) -> TokenResponse:
        """Refresh with rotation: the response carries a new refresh token."""
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def revoke(self, refresh_token: str) -> None:
        """RFC 7009 revocation of a refresh token."""
        response = self._post(
            self.metadata().revocation_endpoint, {"token": refresh_token, "token_type_hint": "refresh_token"}
        )
        if response.status_code != 200:
            raise self._error_from(response)

    def userinfo(self, access_token: str) -> dict[str, Any]:
        """The userinfo claims for an access token."""
        try:
            response = self._http.get(
                self.metadata().userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(f"userinfo request failed: {type(error).__name__}") from error
        if response.status_code != 200:
            raise self._error_from(response)
        body = response.json()
        return body if isinstance(body, dict) else {}

    def _parse_metadata(self, document: Mapping[str, Any]) -> ProviderMetadata:
        missing = [name for name in _REQUIRED if not isinstance(document.get(name), str)]
        if missing:
            raise ProviderUnavailableError(f"the discovery document lacks {', '.join(missing)}")
        if document["issuer"] != self._issuer:
            raise ProviderUnavailableError("the issuer in the discovery document does not match OIDC_ISSUER")
        return ProviderMetadata(**{name: str(document[name]) for name in _REQUIRED})

    def _get_json(self, url: str) -> Mapping[str, Any]:
        last: Exception | None = None
        for delay in (*RETRY_DELAYS, None):
            try:
                response = self._http.get(url)
                if response.status_code < 500:
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        raise ProviderUnavailableError(f"{url} did not return a JSON object")
                    return body
                last = ProviderUnavailableError(f"{url} answered {response.status_code}")
            except httpx.TransportError as error:
                last = error
            except httpx.HTTPStatusError as error:
                raise ProviderUnavailableError(f"{url} answered {error.response.status_code}") from error
            if delay is not None:
                self._sleep(delay)
        raise ProviderUnavailableError(f"could not fetch {url}: {last}")

    def _post(self, url: str, data: Mapping[str, str]) -> httpx.Response:
        body = {"client_id": self._client_id, "client_secret": self._client_secret, **data}
        try:
            return self._http.post(url, data=body)
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(f"request to the provider failed: {type(error).__name__}") from error

    def _token_request(self, data: Mapping[str, str]) -> TokenResponse:
        response = self._post(self.metadata().token_endpoint, data)
        if response.status_code != 200:
            raise self._error_from(response)
        try:
            body = response.json()
            return TokenResponse(
                access_token=str(body["access_token"]),
                refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
                id_token=str(body["id_token"]) if body.get("id_token") else None,
                expires_in=int(body["expires_in"]),
                scope=str(body.get("scope", "")),
            )
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderError("invalid_response", "the token response is not valid") from error

    @staticmethod
    def _error_from(response: httpx.Response) -> ProviderError:
        try:
            body = response.json()
            code = str(body.get("error", f"http_{response.status_code}"))
            description = str(body.get("error_description", ""))
        except ValueError:
            code, description = f"http_{response.status_code}", ""
        _log.warning(
            "provider refused a request",
            extra={"event": "provider.error", "error": code, "status": response.status_code},
        )
        return ProviderError(code, description)
