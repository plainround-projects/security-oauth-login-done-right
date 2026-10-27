# HTTP, cookies, CSRF and security headers

## What it is

**HTTP** is how a browser talks to a web server. It is text, one request and one response at a time, and the server does not remember anything between requests by itself. Three browser features are bolted on to make logins and safety work:

- A **cookie** is a small value the server asks the browser to store (`Set-Cookie`) and send back on every later request to the same site (`Cookie`). It is how a server recognizes "the same browser" again.
- **CSRF** (cross-site request forgery) is an attack in which a *different* website makes your browser send a request to the site you are signed in to. The browser attaches your cookie automatically, so the server thinks you did it.
- **Security headers** are response headers that tell the browser to switch on protections.

None of these is a library. They are protocols and conventions, implemented here in `src/oidc_login/interfaces/http/security.py` and `app.py`.

## Why this repository uses it

OAuth login is a dance between the browser, this app and the provider, and the dance has a famous weak point: the callback. If an attacker can make a victim's browser deliver the attacker's own `code` to the app's `/callback`, the victim ends up signed in as the attacker (**login CSRF**). Cookies are the control: a short-lived cookie ties the callback to the browser that started the login. A second cookie carries the session afterwards. Headers and a CSRF token protect the pages and the two state-changing routes.

## Where it appears

| Path | What it does |
| --- | --- |
| `interfaces/http/security.py` | The two cookie names, `set_cookie`/`clear_cookie`, the header table, the CSP string. |
| `interfaces/http/app.py` | `/login` and `/callback` handle the login cookie; `_require_csrf` guards `/logout` and `/refresh`; `finish` adds headers. |
| `application/login_flow.py` | `_claim_attempt` (cookie + state), `hash_session_id`, `csrf_valid`. |
| `infrastructure/settings.py` | `COOKIE_SECURE`; production refuses `false`. |
| `tests/unit/test_http_app.py` | Cookie flags, headers, the refused callbacks. |
| `src/oidc_login/interfaces/demo_cli.py` | `login_csrf`, `mismatched_state`, `replayed_callback` steps. |

## How it works underneath

**Two cookies with different jobs.**

| Cookie | Set when | Holds | Lifetime | Removed |
| --- | --- | --- | --- | --- |
| `__Host-login` | `GET /login` | The `attempt_id`: a key into the server's pending-login store | 10 minutes (`LOGIN_ATTEMPT_TTL_SECONDS`) | On success or any failed callback |
| `__Host-session` | Successful callback | A random session id; the server stores only its SHA-256 | 8 hours absolute, 15 minutes idle | On sign-out |

Neither cookie holds a token, a name, or any readable data. They are opaque random strings.

**A sign-in, from the cookies' view.**
1. `GET /login`: the server creates the pending login and answers with a redirect to the provider plus `Set-Cookie: __Host-login=<attempt id>`.
2. After the user authenticates, the provider redirects the browser to `/callback?code=...&state=...`. The browser sends `__Host-login` along.
3. The server looks up the attempt by the cookie and compares the `state` in the URL with the one stored for that attempt. An attacker who plants a victim's browser on `/callback?code=ATTACKER&state=ATTACKER` fails: the victim's browser has no matching `__Host-login` cookie.
4. On success the server sets `__Host-session`, clears `__Host-login`, and redirects to `/`.

**SameSite=Lax is a decision, not a default.** `SameSite=Strict` would not send the cookie on the provider's redirect back to the app (a cross-site navigation), so the login cookie would never arrive. `Lax` sends cookies on top-level GET navigations from other sites (exactly the redirect) but not on cross-site POSTs or background requests. That is why the login cookie works, and also why the state-changing routes still need a CSRF token.

### Ideas you need first

- **HTTP and a header.** HTTP is the text protocol of the web. A message is a first line, then header lines (`Name: value`), a blank line, and an optional body. Headers carry metadata: which cookie, what content type, what the browser should and should not do.
- **A cookie.** A small value the server asks the browser to store (header `Set-Cookie: name=value; attributes`) and the browser sends back automatically with every later request to that site (header `Cookie: name=value`). Without cookies the server cannot tell that two requests come from the same person.
- **A cookie attribute.** A setting stored with the cookie: `HttpOnly` (page scripts cannot read it), `Secure` (only sent over HTTPS), `SameSite=Lax` (not sent on cross-site POSTs), `Path=/` (sent for every path), `Max-Age` (seconds to keep it).
- **An origin.** Scheme, host and port together (`https://example.com:443`). Browsers keep pages from different origins apart: a page from another site can make your browser *send* a request to this site but cannot *read* the answer. That asymmetry is why a secret token in a page defeats CSRF.
- **A token.** A random value used as a password-like proof: here a session id and a CSRF token, both 256 bits from the operating system's secure random source.
- **HTTPS.** HTTP wrapped in TLS encryption. This app expects HTTPS to be ended by a proxy in front of it (`TRUSTED_PROXY_COUNT`).

## Walkthrough of this repository's use

### The cookies

```python
SESSION_COOKIE = "__Host-session"
LOGIN_COOKIE = "__Host-login"

def set_cookie(response: Response, name: str, value: str, *, max_age: int, secure: bool) -> None:
    response.set_cookie(name, value, max_age=max_age, httponly=True, secure=secure, samesite="Lax", path="/")
```
- `HttpOnly`: page scripts cannot read it, so an XSS bug cannot steal it.
- `Secure`: sent only over HTTPS. `COOKIE_SECURE` defaults to true; a plain-HTTP local run may set it false, but `Settings._validate` raises `ConfigError("COOKIE_SECURE=false is not accepted in production")`.
- `SameSite=Lax`: see above. `Path=/`, no `Domain`: the cookie belongs to exactly this host.
- The `__Host-` prefix makes the browser *enforce* Secure, `Path=/` and no Domain. (A browser treats `http://localhost` as a secure context, which is why local development with the prefix works in a real browser. The scripted browsers and test client use `https://localhost` or set cookies by hand.)
- `max_age`: seconds the browser keeps the cookie.
- `clear_cookie` calls `delete_cookie` with the same attributes.

### The session id

```python
def hash_session_id(raw_session_id: str) -> str:
    return hashlib.sha256(raw_session_id.encode()).hexdigest()
```
The raw id exists on the server only at the moment it is issued; the store is keyed by the hash, so a memory dump of the store does not contain a usable cookie. Resolving a session also enforces the idle limit and the absolute limit and refreshes `last_seen_at`.

### CSRF for state-changing routes

```python
def _require_csrf(session: UserSession) -> None:
    supplied = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD)
    if supplied is None or not _csrf_matches(session, supplied):
        raise _CsrfRejectedError
```
The token (`X-CSRF-Token` header or `csrf_token` form field) is generated per session and compared with `hmac.compare_digest`. A hostile page can make the browser *send* a POST with your cookie, but cannot *read* your pages, so it cannot learn the token. The only forms in the app (`/logout` on the home page) carry it as a hidden field. `GET` routes never change state.

### Security headers

```python
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Cache-Control": "no-store",
}
```
- **Content-Security-Policy**: `default-src 'none'` forbids loading or running anything not named by a more specific rule, including every script; `style-src 'self'` allows only the app's stylesheet; `form-action 'self'` lets forms post only back to this site; `frame-ancestors 'none'` forbids framing (clickjacking); `base-uri 'none'` stops a `<base>` tag redirecting relative links. The provider's login page is a different site with its own headers.
- **X-Content-Type-Options: nosniff** and **X-Frame-Options: DENY**: no content-type guessing, no frames (older equivalent of `frame-ancestors`).
- **Referrer-Policy: no-referrer**: the comment in the code gives the reason specific to this app: the callback URL carries a one-time code, and the browser must never leak it in a `Referer` header to another site.
- **Cross-Origin-Opener-Policy / Resource-Policy: same-origin** and **Permissions-Policy**: isolate the page and switch off camera, microphone and location.
- **Strict-Transport-Security**: once seen over HTTPS, the browser refuses plain HTTP to this host for two years.
- **Cache-Control: no-store**: neither browser nor proxy keeps a copy of any response; this matters most for the callback and `/me`.

`apply_security_headers` uses `headers.setdefault(...)`, so a handler's own value wins; the `after_request` hook applies it to every response, including errors.

### What the demo and tests show

`mismatched_state`, `login_csrf`, `replayed_callback`: a wrong `state` is refused and no session is created; a valid-looking callback in a browser that did not start the login is refused; a successful callback cannot be replayed (the attempt is single-use). `test_no_token_ever_reaches_the_browser` checks that no response contains a token and the cookies hold only opaque ids.

## Try it yourself

1. Run the HTTP unit tests (no provider):
   ```bash
   .venv/bin/pytest tests/unit/test_http_app.py -v 2>&1 | grep -E "cookie|header|state|csrf|replay|token" | head
   ```
   Expect several `PASSED` lines whose names are the claims above.
2. See the cookie and headers on a live app (`make up`, `make run`):
   ```bash
   curl -si http://localhost:3000/login | head -20
   ```
   Expect a 302, a `Location` to the provider, a `Set-Cookie: __Host-login=...` with `HttpOnly` and `SameSite=Lax` (and `Secure` when `COOKIE_SECURE` is true), and the headers from the table.
3. Make a CSRF failure on purpose (no session, no token):
   ```bash
   curl -si -X POST http://localhost:3000/refresh | head -3
   ```
   Expect a `401` (no session), since the session is checked before the token. With a session and no token, the answer is `403` `csrf_rejected`.
4. Run the scenario (`make up` then `make demo`) and find the steps about state, login CSRF and replay. Expect `PASS`.

## Mistakes people make

- Putting tokens (or any data) in a cookie when a random id and a server-side lookup do the job and can be revoked at once.
- `SameSite=Strict` on the login cookie, which breaks the redirect back; or `None`, which sends it everywhere.
- Skipping `state` or tying it to nothing, so any callback is accepted.
- A CSRF token stored in a cookie the browser sends automatically.
- Using GET for actions that change state.
- A CSP with `unsafe-inline` or `*`.
- Letting the callback URL leak through `Referer` or into logs.

## Check yourself

1. Why is there a `__Host-login` cookie in addition to the `state` parameter?
   *`state` alone could be known to an attacker; the cookie proves the callback arrives in the browser that started the login.*
2. Why `SameSite=Lax` and not `Strict`?
   *The redirect from the provider is a cross-site navigation; `Strict` would withhold the cookie.*
3. What does the server store for a session?
   *The SHA-256 of the cookie value, never the value itself.*
4. Why must `/logout` be POST with a token?
   *Otherwise another site could sign the user out; the token cannot be read cross-site.*
5. What does `Referrer-Policy: no-referrer` protect here?
   *The one-time authorization code in the callback URL.*

## Further reading

- MDN, HTTP cookies: https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies
- MDN, `SameSite`: https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies#samesite
- MDN, CSP: https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP
- OWASP CSRF Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- RFC 9700, OAuth 2.0 Security BCP (CSRF on the redirect): https://www.rfc-editor.org/rfc/rfc9700
