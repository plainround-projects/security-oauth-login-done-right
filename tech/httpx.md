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
