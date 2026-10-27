# Flask 3.1

## What it is

Flask is a **web framework** for Python: a library that turns "an HTTP request arrived" into "call this Python function and send back what it returns". **HTTP** is the text protocol browsers use to talk to servers: a **request** (a method such as GET or POST, a path such as `/callback`, headers, an optional body) goes in, and a **response** (a status code such as 200 or 302, headers, a body) comes out.

Flask is called a **micro**-framework because it gives you routing, request and response objects, templates and hooks, and leaves everything else to you. The pinned version is `flask==3.1.3`.

## Why this repository uses it

In this code Flask is only the **interface layer**: it reads the HTTP request, calls `LoginService`, and turns the result (or a named error) into a response. No login rule lives in Flask code. The rules live in `domain/` and `application/`, which cannot import Flask (enforced by `tech/import-linter.md`). That is why the rules are tested without starting a web server.

## Where it appears

| Path | What it does with Flask |
| --- | --- |
| `src/oidc_login/interfaces/http/app.py` | `create_app(container)`: the application factory, ten routes, hooks, error handlers. |
| `src/oidc_login/interfaces/http/security.py` | Cookie and header helpers on Flask's response objects. |
| `src/oidc_login/interfaces/wsgi.py` | `build_app()`: settings, container, app, for gunicorn. |
| `src/oidc_login/interfaces/http/templates/`, `static/` | Pages and the stylesheet. |
| `src/oidc_login/interfaces/demo_cli.py`, `scripted_browser.py` | Run the same Flask app in-process through its test client. |

## How it works underneath

1. A server (gunicorn) accepts a connection, parses the HTTP text, and calls the Flask app as a **WSGI** application: a Python callable `app(environ, start_response)`. WSGI is the agreed interface between Python web servers and frameworks.
2. Flask builds a `Request`, finds the function whose route matches method and path.
3. **Before-request hooks** run in order; an exception or returned response skips the route.
4. The route function returns a body (or a response, or a redirect). Flask wraps it in a `Response`.
5. **After-request hooks** run and may change the response.
6. If anything raised, Flask looks for an **error handler** for that exception class.
7. `g` is a scratchpad that lives for exactly one request; `request` and `g` look global but are bound to the current request.

### Ideas you need first

- **A client and a server.** A client (a browser, or a program like `curl`) asks; a server (this app) answers. They talk over the network. A **port** is a number (3000 here) that picks which program on a machine receives the connection, like an apartment number inside a building address. `127.0.0.1` is the machine's own address ("localhost"): connections to it never leave the machine.
- **A request.** One message from client to server. It has a **method** (GET reads something, POST sends something new, PATCH changes part of something, DELETE removes it), a **path** (`/callback`), optional **query** text after a `?` (`?scope=reports:read`), **headers** (named pieces of metadata, like `Cookie:` or `Accept:`), and an optional **body** (the data being sent: a form, or JSON).
- **A response.** The reply: a **status code** (200 means OK, 201 created, 204 no content, 302 or 303 "go to another address", 400 bad request, 401 not signed in, 403 forbidden, 404 not found, 413 body too large, 429 too many requests, 500 server error, 503 unavailable), headers, and a body (an HTML page or JSON).
- **JSON.** A text format for data. `{"id": 3, "title": "Groceries"}` is an object with two named values: curly braces hold named values, square brackets hold lists, strings are in double quotes, numbers are bare, and `true`, `false` and `null` are the other values. Python reads it into a dictionary.
- **A form.** An HTML page element that sends the typed values to the server, as a POST with the values URL-encoded in the body (`username=alice&password=...`).
- **A route.** A rule that says "requests for this method and path go to this function". Flask writes it as a decorator: `@app.get("/notes")`. `<int:note_id>` inside a path captures that part and converts it to a whole number.
- **A hook.** A function Flask calls automatically at a fixed moment: `before_request` runs before every route, `after_request` after it.
- **An error handler.** A function Flask calls when an exception of a given class escapes a route. It decides the response.
- **A template.** An HTML file with holes the server fills in (`tech/jinja2-templates.md`).

## Walkthrough of this repository's use

### The factory and its limits

```python
def create_app(container: Container) -> Flask:
    settings = container.settings
    flow = container.flow
    secure = settings.cookie_secure
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
```
A **factory** builds the app on demand, so tests and the demo can wire it to different adapters. `MAX_CONTENT_LENGTH` refuses any request body over 16 KiB with status 413: the only bodies here are tiny forms.

### One before and one after hook

```python
@app.before_request
def load_session() -> None:
    g.started = time.perf_counter()
    g.request_id = uuid.uuid4().hex
    g.session = None if request.endpoint in _PUBLIC else flow.resolve(request.cookies.get(SESSION_COOKIE))
```
Before every route: note the start time and a random request id, and look up the session for the cookie (`healthz`, `readyz` and `static` are `_PUBLIC` and skip the lookup).

```python
@app.after_request
def finish(response: Response) -> Response:
    apply_security_headers(response)
    _log.info("request", extra={"request_id": ..., "method": request.method, "path": request.path,
                                "status": response.status_code, "duration_ms": ..., "subject": ...})
    return response
```
After every route: add the security headers (`tech/http-cookies-csrf-and-headers.md`) and write one structured log line. Note what is **not** logged: query strings (the callback's query holds the one-time code and `state`), cookies and bodies. Only `request.path` is logged.

### Routes

| Route | What it does |
| --- | --- |
| `GET /healthz` | `{"status":"ok"}`: liveness, no provider needed. |
| `GET /readyz` | Calls `container.provider.metadata()`; 503 with a reason if the provider is unreachable. |
| `GET /` | Renders `home.html`: sign-in link, or the signed-in page with a CSRF-protected sign-out form. |
| `GET /login` | Calls `flow.start(request.args.getlist("scope"))`, redirects (302) to the provider, sets the short-lived `__Host-login` cookie. |
| `GET /callback` | Completes the login or shows a generic failure page; on success sets the session cookie, clears the login cookie, redirects to `/`. |
| `POST /logout` | Requires the CSRF token, ends the session, revokes the refresh token, clears the cookie, redirects (303). |
| `GET /me` | JSON: subject, username, scopes, session expiry. Never the tokens. |
| `GET /api/profile` | Gets a fresh-enough access token from the flow (refreshing if needed), calls the provider's userinfo endpoint, returns the claims. |
| `POST /refresh` | CSRF-protected manual token refresh. |
| `GET /reports` | Requires the `reports:read` scope. |

```python
@app.get("/login")
def login() -> ResponseReturnValue:
    started = flow.start(request.args.getlist("scope"))
    response = redirect(started.authorization_url, code=302)
    set_cookie(response, LOGIN_COOKIE, started.attempt_id, max_age=started.max_age_seconds, secure=secure)
    return response
```
`@app.get(path)` is a route that accepts only GET. `request.args.getlist("scope")` reads every `?scope=` value from the query. `redirect(url, code=302)` builds a response with status 302 and a `Location` header. The browser follows it.

### The callback: five failure modes, one generic page

```python
try:
    issued = flow.complete(attempt_id=request.cookies.get(LOGIN_COOKIE), state=request.args.get("state"), code=request.args.get("code"))
except StateMismatchError as error:
    ...  return _failed(400, "This sign-in attempt is not valid. Start again.", secure)
except TokenValidationError as error:
    ...  return _failed(401, "The identity provider's response could not be verified.", secure)
except ProviderError as error:
    ...  return _failed(400, "The identity provider refused the sign-in.", secure)
except ProviderUnavailableError:
    return _failed(502, "The identity provider is not reachable. Try again shortly.", secure)
```
Each named error from the flow becomes one HTTP status and one fixed message. The specific reason (`state`, `nonce`, `signature verification failed`...) goes to the log only, so an attacker learns nothing from the page. `_failed` also clears the login-attempt cookie because the attempt is over either way. If the provider itself sends `?error=...` the route answers 400 without trying to complete.

### CSRF for the two state-changing routes

```python
def _require_csrf(session: UserSession) -> None:
    supplied = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD)
    if supplied is None or not _csrf_matches(session, supplied):
        raise _CsrfRejectedError
```
`/logout` and `/refresh` call it explicitly; `_csrf_matches` uses `hmac.compare_digest`. The sign-out form in `home.html` carries the token in a hidden field.

### Error handlers

`@app.errorhandler(ExceptionClass)` registers a function for that exception. `_UnauthenticatedError` becomes 401 JSON; `_CsrfRejectedError` 403; `InsufficientScopeError` 403 `insufficient_scope`; `SessionNotFoundError` 401; any other `LoginError` 401 `sign_in_required` (or 502 for a provider outage); `HTTPException` (404, 405, 413...) uses the standard name; and the catch-all `Exception` handler logs the stack trace with the request id and returns `{"error":"internal_error","message":"Something went wrong"}`.

### Behind a proxy

`ProxyFix` is added only when `TRUSTED_PROXY_COUNT` is set (`tech/werkzeug.md`).

### Every part of `create_app`

**Setup.** `settings`, `flow` (the `LoginService`), `secure = settings.cookie_secure`; `app = Flask(__name__)`; `MAX_CONTENT_LENGTH = 16 * 1024` (bodies above 16 KiB get 413); `ProxyFix` only if `TRUSTED_PROXY_COUNT` is above 0 (`tech/werkzeug.md`).

**Hook `load_session` (before every request).** Stores the start time (`time.perf_counter()`, a precise stopwatch), a random request id (`uuid.uuid4().hex`) and the session: `None` for the public endpoints (`healthz`, `readyz`, `static`), else `flow.resolve(request.cookies.get("__Host-session"))`.

**Hook `finish` (after every request).** Adds the security headers; writes one JSON log line (request id, method, path, status, duration in ms, the signed-in subject or `None`). It logs `request.path` only, never the query string, because the callback's query holds a one-time code.

**`template_context`.** Gives every template `session` and `csrf_token`.

**The routes**, with the Python behind each:
- `GET /healthz`: `jsonify(status="ok")`.
- `GET /readyz`: calls `container.provider.metadata()`; `ProviderUnavailableError` becomes 503 with the reason, else `{"status":"ready"}`.
- `GET /`: `render_template("home.html", extra_scope="reports:read", reports_allowed=...)`.
- `GET /login`: `flow.start(request.args.getlist("scope"))` (every `?scope=` value), `redirect(url, code=302)`, and `set_cookie` for `__Host-login` with the attempt id and the pending lifetime.
- `GET /callback`: if the query has `error`, log it and answer a generic 400 page; else call `flow.complete(attempt_id=<login cookie>, state=<state>, code=<code>)` inside `try`. The except branches: `StateMismatchError` 400; `TokenValidationError` 401; `ProviderError` 400; `ProviderUnavailableError` 502, each logged with its reason and shown as a fixed sentence by `_failed`, which also clears the login cookie. On success: redirect 302 to `/`, set the session cookie, clear the login cookie.
- `POST /logout`: if there is a session, `_require_csrf` then `flow.sign_out(cookie)` and a log line; always `redirect("/", code=303)` and clear the cookie. (A logout without a session is a harmless redirect.)
- `GET /me`: `_require_session()`; JSON with subject, username, sorted scopes, `session_expires_at` as ISO text. No tokens.
- `GET /api/profile`: `flow.access_token(session)` (refreshing if near expiry), `container.provider.userinfo(token)`, JSON with `sub`, `preferred_username`, `email`.
- `POST /refresh`: session, CSRF, `flow.refresh(session)`, JSON `{refreshed: true, access_token_valid_for_seconds: n}`.
- `GET /reports`: session, then `scopes.require(session.scopes, "reports:read")`.

**Helpers.** `_session()` reads `g.session`; `_require_session()` raises the private `_UnauthenticatedError` when it is `None`; `_require_csrf(session)` takes the token from the `X-CSRF-Token` header or the `csrf_token` form field and raises `_CsrfRejectedError` unless it matches (`hmac.compare_digest`); `_failed(status, message, secure)` renders `error.html` and clears the login cookie.

**Error handlers** (`_register_errors`). `_UnauthenticatedError` 401; `_CsrfRejectedError` 403; `InsufficientScopeError` 403 (and logs `authz.refused`); `SessionNotFoundError` 401; any other `LoginError` 401 `sign_in_required` (a `ProviderUnavailableError` becomes 502); `HTTPException` keeps its own code with the standard name; the catch-all `Exception` logs the traceback with the request id and answers a generic 500.

## Try it yourself

1. List the routes:
   ```bash
   .venv/bin/python - <<'EOF'
   import re, pathlib
   src = pathlib.Path("src/oidc_login/interfaces/http/app.py").read_text()
   for m in re.finditer(r'@app\.(get|post|patch|delete)\("([^"]+)"\)', src):
       print(m.group(1).upper().ljust(5), m.group(2))
   EOF
   ```
   Expect ten lines from `GET /healthz` to `GET /reports`.
2. Run the HTTP-level tests (fakes, no provider):
   ```bash
   .venv/bin/pytest tests/unit/test_http_app.py -q
   ```
   Expect `27 passed`.
3. With the app running (`make up`, then `make run`):
   ```bash
   curl -si http://localhost:3000/login | head -12
   ```
   Expect `302 FOUND`, a `Location:` pointing at the provider's authorization endpoint with `code_challenge_method=S256`, and a `Set-Cookie: __Host-login=...; HttpOnly; Path=/; SameSite=Lax` line (plus `Secure` while `COOKIE_SECURE` is true, the default; a plain-HTTP local run may set it to `false`, and production refuses that).
4. Try a protected route without a session:
   ```bash
   curl -si http://localhost:3000/me
   ```
   Expect `401` and `{"error":"unauthenticated","message":"Sign in first"}`.

## Mistakes people make

- Putting login rules in route functions. Here routes only translate.
- Telling the client why a login failed (it helps attackers). The page is generic; the log has the reason.
- Logging the full URL of the callback, which contains the code.
- Using the development server in production (`tech/gunicorn.md`).
- Forgetting a body-size limit.
- Treating `GET` as safe for actions: sign-out and refresh are POST with a token.

## Check yourself

1. What is WSGI?
   *The interface between a Python web server and a Python web application.*
2. Why does the callback show the same message for several different failures?
   *To avoid telling an attacker which check failed; the reason is in the log.*
3. Which routes need a CSRF token, and why?
   *`POST /logout` and `POST /refresh`; they change state and the browser sends the cookie automatically.*
4. What does `g` hold?
   *Per-request values shared between hooks and routes.*
5. Why is `request.args` never logged?
   *The callback's query string contains the authorization code and `state`.*

## Further reading

- Flask 3.1 documentation: https://flask.palletsprojects.com/en/stable/
- Application factories: https://flask.palletsprojects.com/en/stable/patterns/appfactories/
- Handling application errors: https://flask.palletsprojects.com/en/stable/errorhandling/
- WSGI: https://wsgi.readthedocs.io/
