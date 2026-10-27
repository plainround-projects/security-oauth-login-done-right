# OAuth 2.0 and OpenID Connect

## What it is

**OAuth 2.0** (RFC 6749) is a protocol that lets one program get permission to act for a user at another service, without ever handling the user's password. **OpenID Connect** (OIDC) is a thin layer on top of it that adds one thing: a standard way to learn *who the user is*. Together they are how "Sign in with ..." buttons work.

Four roles, and the names you will see in the code:

- **Resource owner / user**: the person.
- **Client**: the app that wants the user signed in (here, the notes app). A **confidential** client can keep a secret on its server; a **public** client (a browser-only app) cannot.
- **Authorization server / identity provider** (IdP, "the provider"): the service that checks the password and issues tokens (here, Keycloak, `tech/keycloak.md`).
- **User agent**: the browser, which carries messages between the other two by **redirects**.

Four kinds of value:

- **Authorization code**: a short-lived, one-time ticket delivered through the browser.
- **ID token**: a signed statement (a JWT, `tech/jwt-and-jwks.md`) that says who signed in.
- **Access token**: a credential the client presents to an API.
- **Refresh token**: a longer-lived credential that gets new access tokens without asking the user again.

A **scope** is a named permission the client asks for (`openid`, `profile`, `email`, `reports:read`).

## Why this repository uses it

The lesson is "OAuth login done right". Most breaches of OAuth logins come from skipping a check the standard asks for. The repository implements the **authorization code flow with PKCE** (`tech/pkce.md`) and makes each protection visible: the `state` check, the `nonce` check, the exact redirect URI, token validation, refresh-token rotation, revocation at sign-out, and scope checks. Each has a test or a demo step that shows what is refused.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/oidc_login/application/login_flow.py` | `LoginService`: start, complete, resolve, refresh, sign out. |
| `src/oidc_login/infrastructure/oidc_provider.py` | The HTTP side: discovery, authorization URL, token endpoint, revocation, userinfo (`tech/httpx.md`). |
| `src/oidc_login/domain/claims.py`, `scopes.py`, `pkce.py`, `errors.py` | The pure rules: ID-token claim checks, scope allow-list and check, PKCE, named failures. |
| `src/oidc_login/interfaces/http/app.py` | Routes `/login`, `/callback`, `/logout`, `/refresh`, `/me`, `/api/profile`, `/reports`. |
| `idp/realm-demo.json` | The provider side: the clients, scopes and token lifetimes. |
| `src/oidc_login/interfaces/demo_cli.py` | The scenario that shows each protection working. |

## How it works underneath

**The authorization code flow, as this app runs it.**

1. The user clicks "Sign in". The browser requests `GET /login` from the app.
2. The app makes four random values: `state`, `nonce`, a PKCE `code_verifier`, and an `attempt_id`. It stores them in memory under the attempt id. It answers with a redirect to the provider's **authorization endpoint** and sets a short-lived cookie `__Host-login` holding only the attempt id.
3. The browser follows the redirect. The user types the password **at the provider**, never at the app.
4. The provider redirects the browser back to the app's **redirect URI** (`/callback`) with `?code=...&state=...`.
5. The app checks that this callback belongs to a login this browser started (cookie + state), then makes a **back-channel** request, server to server, to the provider's **token endpoint**: the code, the PKCE verifier, and the client's own credentials. The browser is not involved.
6. The provider answers with the tokens. The app verifies the ID token's signature and claims, creates its own session, and sets one opaque cookie. The tokens stay on the server.

**Discovery.** Every OIDC provider publishes a JSON document at `<issuer>/.well-known/openid-configuration` that lists its endpoints and the URL of its signing keys (`jwks_uri`). The app reads it instead of hard-coding URLs.

**Why a code and not a token in the redirect?** The browser URL is visible to history, logs and extensions. A code is useless without the client's credentials and the PKCE verifier, so exposing it is not enough to do harm.

## Walkthrough of this repository's use

### Starting a login

```python
def start(self, extra_scopes: list[str]) -> StartedLogin:
    verifier = self._tokens.token(64)
    pending = PendingLogin(
        attempt_id=self._tokens.token(),
        state=self._tokens.token(),
        nonce=self._tokens.token(),
        code_verifier=verifier,
        scope=requested_scope(extra_scopes, self._config.allowed_extra_scopes),
        created_at=self._clock.now(),
    )
    self._pending.put(pending)
    url = self._provider.authorization_url(
        state=pending.state, nonce=pending.nonce, code_challenge=challenge_for(verifier), scope=pending.scope
    )
```
Four independent random values from `secrets.token_urlsafe`; the verifier uses 64 bytes (an 86-character string). Only `challenge_for(verifier)`, a hash of it, goes to the provider. `requested_scope` builds the scope string.

### The authorization request

```python
query = urlencode({
    "client_id": self._client_id,
    "response_type": "code",
    "redirect_uri": self._redirect_uri,
    "scope": scope,
    "state": state,
    "nonce": nonce,
    "code_challenge": code_challenge,
    "code_challenge_method": "S256",
})
return f"{self.metadata().authorization_endpoint}?{query}"
```
`response_type=code` asks for the code flow (not the older "implicit" flow, which the realm disables). `redirect_uri` is the single registered address. `state` ties the callback to this attempt; `nonce` ties the ID token to it; the last two are PKCE. `urlencode` escapes every value, so none of them can add parameters to the URL.

### Scopes

```python
BASE_SCOPE = "openid profile email"

def requested_scope(extra, allowed):
    wanted = sorted({scope for scope in extra if scope in allowed})
    return " ".join([BASE_SCOPE, *wanted])
```
`openid` makes it an OIDC request (the response includes an ID token). The route `/login?scope=...` accepts extra scopes from the query string, but only those on the allow-list (`OIDC_ALLOWED_EXTRA_SCOPES`, default `reports:read`). Anything else is dropped, so a crafted link cannot widen what the app asks for. `scopes.require(session.scopes, "reports:read")` guards `/reports`: without the scope, 403 `insufficient_scope`.

### The callback

```python
def _claim_attempt(self, attempt_id, state):
    if not attempt_id or not state:
        raise StateMismatchError("the callback is not tied to a login this browser started")
    pending = self._pending.pop(attempt_id)
    if pending is None:
        raise StateMismatchError("unknown or already used login attempt")
    if not hmac.compare_digest(pending.state.encode(), state.encode()):
        raise StateMismatchError("state does not match the login this browser started")
    if self._clock.now() >= pending.created_at + timedelta(seconds=self._config.pending_ttl_seconds):
        raise StateMismatchError("the login attempt expired")
    return pending
```
Four refusals: no cookie or no state (a callback this browser did not start: **login CSRF**, where an attacker feeds a victim the attacker's own code); an attempt id never issued or already used (`pop` removes it, so a **replay** finds nothing); a `state` that does not match (compared in constant time); an attempt older than 10 minutes. Each raises `StateMismatchError`, which the route turns into a generic 400 page. The specific reason goes to the log, not to the user.

### The code exchange and validation

```python
response = self._provider.exchange_code(code=code, code_verifier=pending.code_verifier)
...
claims = self._verifier.verify(response.id_token)
identity = check_id_token_claims(claims, Expectations(issuer=..., client_id=..., nonce=pending.nonce, now=now, leeway=...))
check_access_token_hash(claims, response.access_token)
```
After `exchange_code`, the signature is verified first (`tech/pyjwt.md`), then `check_id_token_claims` runs the checks OpenID Connect Core section 3.1.3.7 lists, in this order, each with its own named error: `iss` equals the configured issuer exactly; `aud` contains this client's id (and, if there are several audiences, `azp` equals it); `exp` has not passed (30 seconds of clock leeway); `iat` is not in the future beyond the leeway; `nonce` equals this attempt's value; `sub` exists. Then `at_hash`, if present, must match the access token. All comparisons are exact, never "starts with".

### Sessions, refresh and sign-out

After validation the app creates its own session: a random id (cookie) whose SHA-256 is the key of an in-memory store, holding the identity, the tokens, a CSRF token and three lifetimes (absolute 8 hours, idle 15 minutes by default).

```python
response = self._provider.refresh(refresh_token)
renewed = replace(current, tokens=self._token_set(response, previous=current.tokens))
```
**Refresh token rotation**: the realm sets `revokeRefreshToken: true` and `refreshTokenMaxReuse: 0`, so every refresh returns a new refresh token and the old one stops working. If the provider refuses (reuse, revocation, expiry), the session is dropped and the user must sign in again. A lock ensures two simultaneous refreshes cannot burn the same token.

```python
self._provider.revoke(session.tokens.refresh_token)
```
**Sign-out** deletes the session, then calls the provider's revocation endpoint (RFC 7009), so the refresh token is dead at the source even if somebody copied it.

### What the provider enforces

`idp/realm-demo.json` (`tech/keycloak.md`) registers `notes-app` with `publicClient: false`, `standardFlowEnabled: true`, `implicitFlowEnabled: false`, `directAccessGrantsEnabled: false`, exactly one redirect URI, `pkce.code.challenge.method: S256`, and default scopes `profile` and `email`, with `reports:read` optional. Access tokens last 120 seconds; authorization codes 60 seconds.

## Try it yourself

(Needs Keycloak: `make up`, which needs Docker and free disk space.)

1. See the discovery document and keys:
   ```bash
   make idp-check
   ```
   Expect `issuer`, `authorization_endpoint`, `jwks_uri` and `signing keys` lines.
2. Run the whole scenario and read the checked steps:
   ```bash
   make demo
   ```
   Expect 16 numbered lines, each `PASS`, and a last line `16 of 16 checks passed`. The titles (from the verified run) are: 1 the provider's discovery document and signing keys are reachable; 2 the app sends the browser to the provider with state, nonce and an S256 challenge; 3 the user authenticates at the provider and is redirected to the one registered URI; 4 the code is exchanged on the server and the browser gets only an opaque session cookie; 5 the ID token validator rejects five bad tokens, each for its own reason; 6 the session shows who signed in, never a token; 7 a refresh rotates the refresh token and the old one is refused; 8 after sign-out the old session and the old refresh token are both refused; 9 a callback with a mismatched state is refused; 10 a callback from a browser that did not start the login is refused; 11 a callback cannot be replayed; 12 a lookalike redirect URI is refused by the provider itself; 13 a code cannot be exchanged a second time; 14 a stolen code is useless without the PKCE verifier; 15 a route that needs the reports:read scope refuses a sign-in without it; 16 a public client (no secret) cannot exchange a code without the PKCE verifier. Under each title a detail line shows the evidence, for example for step 14 `exchange with another verifier: invalid_grant (PKCE verification failed: Code mismatch)`.
3. Unit tests need no provider and show the rules alone:
   ```bash
   .venv/bin/pytest tests/unit/test_claims.py tests/unit/test_login_flow.py -q
   ```
   Expect all to pass.
4. Read the authorization URL the app builds, without a provider, from the unit tests:
   ```bash
   grep -n "code_challenge_method" -r tests/unit | head -3
   ```
   Expect a line asserting `S256`.

## Mistakes people make

- Skipping `state` (login CSRF) or using a guessable one.
- Skipping `nonce` or not comparing it, which allows a stolen ID token to be replayed into another login.
- Treating the ID token as an access token, or the access token as proof of identity.
- Accepting any `aud` or `iss`, or matching them by prefix.
- Using the implicit flow or putting tokens in URLs.
- Wildcard or look-alike redirect URIs. The provider here has exactly one and refuses others (the demo shows it).
- Storing tokens in browser storage. They stay on the server here.
- Not rotating or revoking refresh tokens.
- Letting a URL parameter widen the requested scopes.

## Check yourself

1. Why does the app send the browser away to log in?
   *So the user's password is typed only at the provider, never at the app.*
2. What does the `state` value protect against?
   *Callbacks that do not belong to a login this browser started (login CSRF) and replays.*
3. What does the `nonce` protect against?
   *An ID token from another login being substituted into this one.*
4. Where do the tokens live?
   *On the server, in the session store; the browser holds one opaque cookie.*
5. What happens to the old refresh token after a refresh?
   *It is revoked by rotation; reusing it fails.*

## Further reading

- RFC 6749, OAuth 2.0: https://www.rfc-editor.org/rfc/rfc6749
- OpenID Connect Core 1.0 (ID token validation, section 3.1.3.7): https://openid.net/specs/openid-connect-core-1_0.html
- RFC 9700, OAuth 2.0 Security Best Current Practice: https://www.rfc-editor.org/rfc/rfc9700
- RFC 7009, token revocation: https://www.rfc-editor.org/rfc/rfc7009
- OpenID Connect Discovery 1.0: https://openid.net/specs/openid-connect-discovery-1_0.html
