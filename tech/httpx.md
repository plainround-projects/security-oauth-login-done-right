# httpx 0.28

## What it is

httpx is a Python library for **making** HTTP requests: you give it a URL and some data, it opens a network connection, sends the request, waits for the reply and gives you back a `Response` object with `.status_code`, `.headers`, `.text` and `.json()`. It is similar to the well-known `requests` library, and it also has an `async` mode (not used here). Pinned: `httpx==0.28.1`, which depends on `httpcore`, `h11` (the HTTP/1.1 text parser), `anyio`, `certifi` (trusted certificate authorities) and `idna`.

## Why this repository uses it

OpenID Connect has a **back channel**: calls from the app's server straight to the provider's server, without the browser. Fetching the discovery document and the signing keys, exchanging the authorization code for tokens, refreshing tokens, revoking a token and calling the userinfo endpoint are all such calls. The lesson cares about how they are made: with timeouts, without following redirects, with retries only where retrying is safe, and without ever logging the secrets they carry.

## Where it appears

| Path | What it does with httpx |
| --- | --- |
| `src/oidc_login/infrastructure/oidc_provider.py` | `OidcProvider`: one long-lived `httpx.Client`, GET with retries, POST without retries. |
| `src/oidc_login/interfaces/scripted_browser.py` | `ProviderBrowser`: plays the user at the provider's login page (a separate client with hand-kept cookies). |
| `src/oidc_login/interfaces/demo_cli.py` | Two direct `httpx.post` calls to prove the public-client rule. |
| `tests/unit/test_oidc_provider.py` | `httpx.MockTransport`: the provider adapter tested with no network at all. |
| `tests/integration/*.py` | Direct calls to the live Keycloak for set-up checks. |

## How it works underneath

1. A `Client` keeps a **connection pool**: open TCP (and TLS, for `https`) connections reused across requests, so the handshake cost is paid once.
2. `client.get(url)` / `client.post(url, data=...)` writes the request as text. `data={...}` sends a form body (`application/x-www-form-urlencoded`), which is what OAuth token endpoints require.
3. Four **timeouts** apply: `connect` (opening the connection), `read` (waiting for data), `write`, `pool` (waiting for a free pooled connection). Exceeding one raises a `TimeoutException`.
4. Errors form a family: `httpx.HTTPError` is the base; `httpx.TransportError` covers network and timeout failures (`ConnectError`, `ReadTimeout`); `httpx.HTTPStatusError` is raised only if you call `response.raise_for_status()` and the status is 4xx/5xx.
5. A **transport** is the layer that actually moves bytes. Replace it with `httpx.MockTransport(handler)` and the client calls your Python function instead of the network.

### Ideas you need first

- **An HTTP client.** A program (or library) that sends requests to a server and reads the reply: the same role a browser plays, without the page.
- **A connection and a timeout.** To talk to a server, the client opens a connection over the network. A timeout is a limit on how long to wait for each step; without one a stuck server would freeze the caller forever.
- **A redirect.** A reply that says "go to this other address". A client may follow it automatically; here it is turned off.
- **Idempotent.** A request that is safe to send twice because it only reads (GET). Safe-to-repeat requests may be retried after a failure; a request that consumes something (an authorization code) may not.
- **A mock.** A fake server inside the test that answers from a script, so tests need no network.

## Walkthrough of this repository's use

```python
self._http = http or httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=3), follow_redirects=False)
```
A client with a 10-second default timeout (`OIDC_HTTP_TIMEOUT_SECONDS`), 3 seconds to connect, and **no redirect following**: if the provider answered a back-channel call with a redirect, something is wrong, and following it could send the client secret to another host. The `http` parameter lets tests inject a client with a mock transport.

```python
RETRY_DELAYS = (0.2, 0.5, 1.0)
...
for delay in (*RETRY_DELAYS, None):
    try:
        response = self._http.get(url)
        if response.status_code < 500:
            response.raise_for_status()
            body = response.json()
            ...
            return body
        last = ProviderUnavailableError(f"{url} answered {response.status_code}")
    except httpx.TransportError as error:
        last = error
    except httpx.HTTPStatusError as error:
        raise ProviderUnavailableError(f"{url} answered {error.response.status_code}") from error
    if delay is not None:
        self._sleep(delay)
```
The **idempotent** reads (discovery, keys; safe to repeat) retry on network errors and 5xx answers, waiting 0.2, 0.5 and 1.0 seconds; a 4xx answer fails at once. The loop runs four times; the final `None` means "no delay, this was the last attempt". `sleep` is an injected parameter so the tests do not wait.

```python
def _post(self, url, data):
    body = {"client_id": self._client_id, "client_secret": self._client_secret, **data}
    try:
        return self._http.post(url, data=body)
    except httpx.HTTPError as error:
        raise ProviderUnavailableError(f"request to the provider failed: {type(error).__name__}") from error
```
The token, refresh and revocation calls are **never retried**: the module docstring explains why. An authorization code works once, so a retry of an exchange that actually succeeded would fail and hide the first error. The error message uses only the exception's class name, not its text, so a URL or credential in the text cannot reach a log. The client authenticates in the body (`client_secret_post`).

```python
code = str(body.get("error", f"http_{response.status_code}"))
description = str(body.get("error_description", ""))
```
Provider errors come back as JSON `{"error": "invalid_grant", "error_description": "..."}`. They become a `ProviderError(code, description)` that the flow and the routes map to a generic 400; the log records the code but not the description.

### The scripted browser

`ProviderBrowser` keeps the provider's cookies **by hand** (a dictionary, set from each `Set-Cookie` header). Keycloak marks some cookies `Secure` even on `http://localhost`; a real browser accepts that for localhost but a plain client's cookie jar drops them. It uses a 300-second default timeout because Keycloak's first login on a loaded machine can be very slow. A tiny `HTMLParser` finds the login form's action URL and hidden fields.

### Testing without a network

```python
transport = httpx.MockTransport(handler)
provider = OidcProvider(..., http=httpx.Client(transport=transport), sleep=lambda _: None)
```
The handler is a function from request to `httpx.Response`. The tests assert on the exact request (the `code_verifier` is in the body, the `Authorization` header is on userinfo), simulate 503s and read timeouts, and check that the POSTs are not retried.

### Line by line: `src/oidc_login/infrastructure/oidc_provider.py`

This file talks to Keycloak (or any OpenID Connect provider) over HTTP. **HTTP** is the request and response protocol of the web. A **client** program sends a request (a method such as GET or POST, an address, headers, perhaps a body) and gets a response (a status number such as 200 or 400, headers, a body).

```python
"""The OpenID Connect provider over HTTP: discovery, the authorization URL, and the back-channel calls.

Back-channel POSTs (code exchange, refresh, revoke) are never retried: a second exchange of the same code fails by
design, and a retry would only hide the first error. Idempotent GETs (discovery, keys) retry with backoff.
"""
```

The docstring: discovery, the authorization address and the back-channel calls. The back-channel POSTs (code exchange, refresh, revoke) are never retried: a second exchange of the same code fails by design, and a retry would only hide the first error. Idempotent GETs (discovery, keys), which are safe to repeat, retry with a pause between tries.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode
```

Imports: `logging`, `threading` (a lock), `time`, `Callable` and `Mapping`, `Any` and `urlencode` (turns a dictionary into `name=value&name=value` query text with escaping).

```python
import httpx
```

`httpx` is the HTTP client library (`tech/httpx.md`).

```python
from oidc_login.domain.errors import ProviderError, ProviderUnavailableError
from oidc_login.domain.models import ProviderMetadata, TokenResponse
```

Imports of the two provider errors and the records.

```python
_log = logging.getLogger("oidc_login.provider")
RETRY_DELAYS = (0.2, 0.5, 1.0)
```

`_log` is the logger `oidc_login.provider`. `RETRY_DELAYS` are the pauses before each retry of a GET: 0.2, 0.5 and 1.0 seconds.

```python
_REQUIRED = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
    "userinfo_endpoint",
    "revocation_endpoint",
)
```

`_REQUIRED` lists the six fields the app needs from the discovery document: the issuer and the authorization, token, JWKS, userinfo and revocation addresses.

```python
class OidcProvider:
    """The ``IdentityProvider`` port over httpx, for a confidential client registered with one redirect URI."""
```

`OidcProvider` is the adapter for the `IdentityProvider` port, for a **confidential client** (an app that can keep a secret on its server) registered with exactly one redirect address.

```python
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
```

The constructor takes keyword-only arguments: the expected issuer; the base address where discovery is fetched (may differ from the issuer in Docker, where the app reaches Keycloak by an internal name); the client id and secret; the redirect address; a timeout; an optional ready-made HTTP client (tests pass a fake transport) and a `sleep` function (tests pass a fake to avoid waiting).

```python
        self._issuer = issuer
        self._discovery_url = f"{discovery_base}/.well-known/openid-configuration"
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
```

The discovery address is the base plus `/.well-known/openid-configuration`, the fixed path where OpenID Connect providers publish their description.

```python
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=3), follow_redirects=False)
        self._sleep = sleep
```

The HTTP client is created with a timeout (connect timeout 3 seconds) and `follow_redirects=False`, so a redirect cannot silently send the client secret somewhere else.

```python
        self._metadata: ProviderMetadata | None = None
        self._lock = threading.Lock()
```

The cached metadata starts as `None`, and a lock protects it from two threads fetching at once.

```python
    def close(self) -> None:
        """Close the HTTP client (graceful shutdown)."""
        self._http.close()
```

`close` closes the HTTP client for a clean shutdown.

```python
    def metadata(self) -> ProviderMetadata:
        """The validated discovery document, fetched once and cached."""
        with self._lock:
            if self._metadata is None:
                self._metadata = self._parse_metadata(self._get_json(self._discovery_url))
            return self._metadata
```

`metadata` fetches, validates and caches the discovery document; later calls reuse it. The lock makes concurrent callers wait for the first fetch.

```python
    def jwks(self) -> Mapping[str, Any]:
        """The provider's published signing keys."""
        return self._get_json(self.metadata().jwks_uri)
```

`jwks` fetches the provider's published signing keys from the address in the metadata.

```python
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
```

`authorization_url` builds the address to send the browser to: the client id, `response_type=code` (the code flow), the redirect address, the scope, the state, the nonce, the PKCE challenge and `code_challenge_method=S256`. `urlencode` escapes the values. The result is the provider's authorization endpoint plus `?` plus that query.

```python
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
```

`exchange_code` posts `grant_type=authorization_code` with the code, the exact redirect address and the PKCE verifier. The provider checks that the hash of the verifier matches the challenge it saw. The browser never sees this request.

```python
    def refresh(self, refresh_token: str) -> TokenResponse:
        """Refresh with rotation: the response carries a new refresh token."""
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
```

`refresh` posts `grant_type=refresh_token` with the refresh token; the provider answers with a new refresh token (rotation).

```python
    def revoke(self, refresh_token: str) -> None:
        """RFC 7009 revocation of a refresh token."""
        response = self._post(
            self.metadata().revocation_endpoint, {"token": refresh_token, "token_type_hint": "refresh_token"}
        )
        if response.status_code != 200:
            raise self._error_from(response)
```

`revoke` posts the token with the hint `refresh_token` to the revocation endpoint (RFC 7009). Any status other than 200 becomes a `ProviderError`.

```python
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
```

`userinfo` sends a GET with the header `Authorization: Bearer <access token>`. A transport failure becomes `ProviderUnavailableError` with only the error's class name (no secrets in the message); a non-200 answer becomes a `ProviderError`; the JSON body is returned if it is an object, else an empty dictionary.

```python
    def _parse_metadata(self, document: Mapping[str, Any]) -> ProviderMetadata:
        missing = [name for name in _REQUIRED if not isinstance(document.get(name), str)]
        if missing:
            raise ProviderUnavailableError(f"the discovery document lacks {', '.join(missing)}")
        if document["issuer"] != self._issuer:
            raise ProviderUnavailableError("the issuer in the discovery document does not match OIDC_ISSUER")
        return ProviderMetadata(**{name: str(document[name]) for name in _REQUIRED})
```

`_parse_metadata` lists the required fields that are missing or not text and raises if any are missing. It then requires the document's `issuer` to equal the configured issuer exactly: a discovery document from the wrong provider is refused. It builds the `ProviderMetadata` from the six fields.

```python
    def _get_json(self, url: str) -> Mapping[str, Any]:
        last: Exception | None = None
```

`_get_json` fetches a JSON document with retries; `last` remembers the latest error.

```python
        for delay in (*RETRY_DELAYS, None):
            try:
                response = self._http.get(url)
```

The loop goes through the three delays and then `None` (the final try with no further wait) and does a GET.

```python
                if response.status_code < 500:
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        raise ProviderUnavailableError(f"{url} did not return a JSON object")
                    return body
```

A status below 500 is final: `raise_for_status` turns 4xx into an error, and a JSON object is returned (anything else raises).

```python
                last = ProviderUnavailableError(f"{url} answered {response.status_code}")
            except httpx.TransportError as error:
                last = error
```

A 5xx status or a transport error (network down, timeout) is remembered and retried.

```python
            except httpx.HTTPStatusError as error:
                raise ProviderUnavailableError(f"{url} answered {error.response.status_code}") from error
```

A 4xx status is not retried and becomes `ProviderUnavailableError` with the status.

```python
            if delay is not None:
                self._sleep(delay)
        raise ProviderUnavailableError(f"could not fetch {url}: {last}")
```

Between tries it sleeps; after the last one it raises "could not fetch" with the last error.

```python
    def _post(self, url: str, data: Mapping[str, str]) -> httpx.Response:
        body = {"client_id": self._client_id, "client_secret": self._client_secret, **data}
        try:
            return self._http.post(url, data=body)
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(f"request to the provider failed: {type(error).__name__}") from error
```

`_post` adds the client id and client secret to the form body of every back-channel POST and sends it; a transport failure becomes `ProviderUnavailableError`. The secret travels in the body to the provider's token endpoint, never through the browser.

```python
    def _token_request(self, data: Mapping[str, str]) -> TokenResponse:
        response = self._post(self.metadata().token_endpoint, data)
        if response.status_code != 200:
            raise self._error_from(response)
```

`_token_request` posts to the token endpoint; a non-200 answer becomes a `ProviderError`.

```python
        try:
            body = response.json()
            return TokenResponse(
                access_token=str(body["access_token"]),
                refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
                id_token=str(body["id_token"]) if body.get("id_token") else None,
                expires_in=int(body["expires_in"]),
                scope=str(body.get("scope", "")),
            )
```

The JSON is turned into a `TokenResponse`: the access token, the refresh and ID tokens if present, `expires_in` as a number and the scope.

```python
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderError("invalid_response", "the token response is not valid") from error
```

A missing or malformed field raises `ProviderError("invalid_response", ...)`.

```python
    @staticmethod
    def _error_from(response: httpx.Response) -> ProviderError:
        try:
            body = response.json()
            code = str(body.get("error", f"http_{response.status_code}"))
            description = str(body.get("error_description", ""))
        except ValueError:
            code, description = f"http_{response.status_code}", ""
```

`_error_from` reads an OAuth error body: the `error` code and `error_description`. A body that is not JSON gives the code `http_<status>`.

```python
        _log.warning(
            "provider refused a request",
            extra={"event": "provider.error", "error": code, "status": response.status_code},
        )
        return ProviderError(code, description)
```

A warning is logged with the error code and status (not the description, which could echo input), and a `ProviderError` is returned.

## Try it yourself

1. Version and timeouts:
   ```bash
   .venv/bin/python -c "import httpx; print(httpx.__version__, httpx.Timeout(10, connect=3))"
   ```
   Expect `0.28.1 Timeout(connect=3, read=10, write=10, pool=10)`.
2. Run the adapter tests with no network:
   ```bash
   .venv/bin/pytest tests/unit/test_oidc_provider.py -q
   ```
   Expect all to pass.
3. A mock transport in five lines:
   ```bash
   .venv/bin/python -c "
   import httpx
   c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'path': r.url.path})))
   print(c.get('http://provider.test/a/b').json())"
   ```
   Expect `{'path': '/a/b'}`.
4. Watch a timeout behave (needs nothing running on the port):
   ```bash
   .venv/bin/python -c "
   import httpx
   try: httpx.get('http://127.0.0.1:9', timeout=1)
   except httpx.TransportError as e: print(type(e).__name__)"
   ```
   Expect `ConnectError`.

## Mistakes people make

- No timeout: one hung provider freezes every request thread.
- Following redirects on calls that carry credentials.
- Retrying a request that is not safe to repeat (a code exchange).
- Putting `response.text` or the full exception message in logs when the request had a secret.
- Creating a new `Client` per request, which throws away connection reuse.
- Using one cookie jar for two different sites, or relying on a jar's rules for `Secure` cookies on `http://localhost`.

## Check yourself

1. Why are the code exchange and refresh calls not retried?
   *An authorization code works once; a retry after a success would fail and hide the real outcome.*
2. Why `follow_redirects=False`?
   *A redirect on a call that carries the client secret could send it elsewhere.*
3. What does `MockTransport` replace?
   *The network: the client calls a Python function instead.*
4. Which two kinds of provider failure retry?
   *Network errors (`TransportError`) and 5xx answers, on the idempotent GET calls only.*
5. What are the four timeouts?
   *connect, read, write and pool.*

## Further reading

- httpx documentation (0.28): https://www.python-httpx.org/
- Timeouts: https://www.python-httpx.org/advanced/timeouts/
- Mock transports for testing: https://www.python-httpx.org/advanced/transports/#mock-transports
- RFC 6749 section 3.2 (the token endpoint): https://www.rfc-editor.org/rfc/rfc6749#section-3.2
