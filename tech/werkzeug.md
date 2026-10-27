# Werkzeug 3.1

## What it is

Werkzeug is the library underneath Flask. It implements the details of HTTP in Python: parsing a request, building a response, cookies, headers, routing URLs to functions, a test client, and middleware. **Middleware** is a wrapper around a WSGI application that can change the request on the way in and the response on the way out. Flask imports Werkzeug automatically, so it is installed as Flask's dependency and pinned in the lock file (`werkzeug==3.1.9`).

## Why this repository uses it

Four small, visible uses: the `HTTPException` base class (so one error handler can catch every standard HTTP error), the `ProxyFix` middleware (to learn the real scheme and client address behind a reverse proxy), the `Response` class that carries the cookie and header helpers, and the **test client** (to drive the whole app without opening a network port).

## Where it appears

| Path | What it does with Werkzeug |
| --- | --- |
| `src/oidc_login/interfaces/http/app.py` | `from werkzeug.exceptions import HTTPException` and `from werkzeug.middleware.proxy_fix import ProxyFix`. |
| `src/oidc_login/interfaces/http/security.py` | `from werkzeug.wrappers import Response`: `set_cookie` and `delete_cookie` are Werkzeug's. |
| `src/oidc_login/interfaces/scripted_browser.py` | `from werkzeug.test import TestResponse`; `AppBrowser` wraps `app.test_client()`, which is Werkzeug's client. |

## How it works underneath

1. A reverse proxy (a server in front of your app, such as nginx or a cloud load balancer) accepts the browser's connection and opens a new one to your app. From the app's point of view every request now comes from the proxy's address.
2. To keep the real address, the proxy adds a header: `X-Forwarded-For: <client address>` (and `X-Forwarded-Proto: https`). Each proxy in a chain appends its own entry.
3. Anyone can also *send* an `X-Forwarded-For` header themselves. So an app must only believe the entries added by proxies it trusts.
4. `ProxyFix(app, x_for=N)` says "trust exactly N proxies" and rewrites `request.remote_addr` from the Nth entry from the right.

### Ideas you need first

- **A reverse proxy.** A server that sits in front of your app: browsers talk to it, and it forwards each request to your app and relays the answer. It often handles HTTPS (so the app itself sees plain HTTP), spreads load over several copies of the app, or adds protections. From the app's point of view every request now appears to come from the proxy's address.
- **A request header.** A named piece of metadata in a request. A proxy adds `X-Forwarded-For` (the client's real address) and `X-Forwarded-Proto` (`https` or `http`, the scheme the client used). Anyone can also send these headers by hand, so an app should only believe them when it knows a trusted proxy sets them.
- **Middleware.** A wrapper around an application that can inspect and change each request on the way in and each response on the way out.
- **A test client.** A fake browser that calls the application directly, without a network, and returns the response. It also keeps cookies between requests.

## Walkthrough of this repository's use

### `ProxyFix`

```python
if settings.trusted_proxy_count:
    app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
        app.wsgi_app, x_for=settings.trusted_proxy_count, x_proto=settings.trusted_proxy_count
    )
```
`settings.trusted_proxy_count` comes from the environment variable `TRUSTED_PROXY_COUNT` (default 0, meaning "no proxy, believe nothing"). `app.wsgi_app` is the inner WSGI callable inside Flask; wrapping it puts `ProxyFix` in front of Flask's own handling. `x_for` is how many `X-Forwarded-For` entries to trust; `x_proto` does the same for `X-Forwarded-Proto` so Flask knows the original scheme was `https`. The comment `# type: ignore[method-assign]` silences `mypy`, which dislikes reassigning a method; this is the documented way to apply the middleware.

Why it matters here: the app builds its cookies with `Secure` and the provider's redirect URI uses `https` in production. Behind a TLS-terminating proxy, the connection to the app is plain HTTP, so without `x_proto` Flask would believe the request was insecure. Setting the count correctly makes Flask see the original scheme (and client address); setting it too high lets a client forge those headers. The default is 0, "believe nothing".

### `HTTPException`

```python
@app.errorhandler(HTTPException)
def http_error(error: HTTPException) -> ResponseReturnValue:
    return jsonify(error=error.name.lower().replace(" ", "_"), message=error.name), error.code or 500
```
Every standard HTTP error that Werkzeug raises (404 for an unknown path, 405 for a wrong method, 413 for a body over the 16 KiB limit) is an `HTTPException` with a `code` and a `name` such as `Not Found`. One handler turns all of them into the same JSON shape, using the name and never any internal text.

### Cookies on a `Response`

```python
def set_cookie(response: Response, name: str, value: str, *, max_age: int, secure: bool) -> None:
    response.set_cookie(name, value, max_age=max_age, httponly=True, secure=secure, samesite="Lax", path="/")
```
Werkzeug's `Response.set_cookie` writes the `Set-Cookie` header with the attributes asked for (`tech/http-cookies-csrf-and-headers.md`); `delete_cookie` sends the same cookie name with an expired date.

### The test client

```python
class AppBrowser:
    def __init__(self, app: Flask) -> None:
        self.client = app.test_client()

    def request(self, method: str, path: str, **kwargs: Any) -> TestResponse:
        kwargs.setdefault("base_url", "https://localhost")
        return self.client.open(path, method=method, **kwargs)
```
`app.test_client()` builds a fake WSGI environment and calls the app directly, with a **cookie jar** (it remembers `Set-Cookie` headers and sends them back, like a browser). `base_url="https://localhost"` matters: the session cookie is `Secure`, and the client only returns a Secure cookie to an `https` URL. The demo and the integration tests use this to play "the user's browser at the app" while a separate `ProviderBrowser` plays the user at Keycloak.

## Try it yourself

1. Watch `ProxyFix` change the visible scheme:
   ```bash
   .venv/bin/python - <<'EOF'
   from flask import Flask, request
   from werkzeug.middleware.proxy_fix import ProxyFix
   app = Flask(__name__)
   @app.get("/")
   def home(): return request.scheme
   headers = {"X-Forwarded-Proto": "https"}
   plain = app.test_client().get("/", headers=headers)
   app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
   fixed = app.test_client().get("/", headers=headers)
   print(plain.text, fixed.text)
   EOF
   ```
   Expect `http https`: the header is ignored until `ProxyFix` is applied.
2. See the body limit:
   ```bash
   .venv/bin/python -m pytest tests/unit/test_http_app.py -q -k oversized 2>&1 | tail -2
   ```
   Expect `1 passed`: a 20,000-byte form body gets status 413 in the JSON error shape.
3. Look at an `HTTPException`:
   ```bash
   .venv/bin/python -c "from werkzeug.exceptions import NotFound; e = NotFound(); print(e.code, e.name)"
   ```
   Expect `404 Not Found`.

## Mistakes people make

- Trusting `X-Forwarded-For` when there is no proxy, or trusting too many entries. The default here is zero.
- Calling the test client with `http://` and wondering why Secure cookies vanish.
- Assuming the request is `http` when a proxy terminated TLS in front of the app, or trusting a forwarded header when no proxy exists. See the section above.

## Check yourself

1. What is middleware?
   *A wrapper around a WSGI app that can change requests before and responses after.*
2. What does `x_for=1` mean?
   *Trust exactly one proxy and take the address from the last `X-Forwarded-For` entry it added.*
3. Why does the test `AppBrowser` use `https://localhost`?
   *The session cookie is `Secure`; the client only sends it back over https.*
4. What does `HTTPException.code` hold?
   *The numeric HTTP status, such as 404.*
5. Why default `TRUSTED_PROXY_COUNT` to 0?
   *Believing a forwarded header from the open internet lets an attacker forge their address.*

## Further reading

- Werkzeug 3.1 documentation: https://werkzeug.palletsprojects.com/en/stable/
- Middleware, `ProxyFix`: https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/
- Test client: https://werkzeug.palletsprojects.com/en/stable/test/
