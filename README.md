# security-oauth-login-done-right

Sign-in for a small server-side app with an identity provider you run yourself (Keycloak in a container): the authorization code flow with PKCE, ID tokens validated for signature, issuer, audience, expiry and nonce, a short-lived server-side session with refresh-token rotation, and sign-out that revokes the refresh token. Then each protection is shown by what is refused when it fires, so the baseline is understood, not copied.

| | |
| --- | --- |
| **Lesson** | `/prep/security/project-oauth-login-done-right`, "Add sign-in with the code flow and PKCE" (`data-structure-explainer/src/content/tracks/security/24-project-oauth-login-done-right.md` in the Plainround app) |
| **Planned hours** | 10 |
| **Level** | Intermediate |
| **Architecture** | [ARCHITECTURE.md](ARCHITECTURE.md); decisions: [docs/adr](docs/adr) |
| **Technology notes** | [tech/](tech/README.md): one beginner-level note per technology used here (OAuth 2.0 and OpenID Connect, PKCE, JWT, Keycloak, Python, Flask, Docker and the rest), written through this repository's own files |

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-dark.svg">
  <img alt="A browser talks to a Flask app in one gunicorn process, which hands the flow to LoginService; the user signs in at Keycloak, LoginService exchanges the code, checks tokens against the JWKS keys and keeps them in the session store." src="docs/diagrams/architecture.svg">
</picture>

Only two opaque cookies reach the browser; every token stays in the server-side session store, and each check has a refusal drawn in amber.

## How one run flows

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/flow-dark.svg">
  <img alt="The run goes from GET /login through the provider, the callback, the token exchange and validation, to a session, a refresh and a revoking sign-out." src="docs/diagrams/flow.svg">
</picture>

The amber row shows a callback with the wrong state or from another browser refused with a 400 before the provider is called.

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| Docker with Compose v2 | 24 or newer (tested with 24.0.6) | Keycloak |
| Python | 3.12 or 3.13 (tested with 3.13; the CI uses 3.12) | the app and the tests |
| GNU Make and curl | Make 3.81 or newer | every command below |
| Keycloak image | `quay.io/keycloak/keycloak:26.4`, development mode | pulled on first `make up`; the first start takes a minute or two on a quiet machine |
| Python packages | Flask 3, gunicorn, httpx and PyJWT with cryptography at run time; pytest, pytest-cov, ruff, mypy, import-linter, pip-audit, cyclonedx-bom for development. All pinned with hashes in `requirements.lock` and `requirements-dev.lock`; `make` installs them into `.venv/` | everything |

No cloud account. Every credential is read from the environment: `make up` copies `.env.example` to `.env` the first time (throwaway values for a provider that lives on this machine while its container runs: the admin password, the client secret, the test user's password). Ports 8180 (Keycloak; set `KEYCLOAK_PORT` and `OIDC_ISSUER` together to change it) and 3000 (the app, fixed by the one registered redirect URI `http://localhost:3000/callback`) must be free.

A browser note: the session cookie is `Secure` (the `__Host-` prefix requires it). Chrome and Firefox accept it on `http://localhost`; Safari does not. The tests and `make demo` do not need a browser.

## Setup, run, test, stop

```bash
make up                  # Keycloak with the demo realm imported; waits until it answers, then prints the discovery document
make run                 # the app on http://localhost:3000 (gunicorn, one worker; Ctrl-C shuts it down gracefully)
make demo                # the lesson's scenario against the live provider: sign-in, every protection, refresh, sign-out
make check               # format check, lint with security rules, types, import rules, unit tests with coverage (no provider)
make test-integration    # token validation, flow protections, session lifecycle against Keycloak (needs make up)
make test-e2e            # a real server process, a scripted browser, SIGTERM, refusal to start (needs make up)
make test-all            # unit, integration and end-to-end
make audit               # known-vulnerability check of the locked dependencies
make sbom                # sbom.cdx.json (CycloneDX) for the runtime dependencies
make health              # exit 0 when the running app answers /healthz
make docker-run          # the image next to Keycloak, healthy before it returns
make down                # stops the containers and deletes their data
```

`make help` lists every target. Operational log lines are JSON on standard error; tokens, codes, secrets and cookies are redacted by field name. Keycloak's first start in a fresh container runs a one-time build step that can take several minutes on a heavily loaded machine; `make up` waits for it (the health check allows ten minutes).

To try it in a browser: `make up`, `make run`, open `http://localhost:3000`, choose "Sign in", and use the user `demo-user` with the password from `DEMO_USER_PASSWORD` in `.env`.

## The identity provider's configuration

There is no SQL: the provider's state is one file, [idp/realm-demo.json](idp/realm-demo.json), imported at start. It defines:

- the realm `demo` with access tokens of 2 minutes, refresh-token rotation on (`revokeRefreshToken`, no reuse) and brute-force protection;
- the client `notes-app`: confidential, standard flow only (no implicit, no password grant), PKCE S256 required, exactly one redirect URI;
- the client `notes-spa` (stretch): public, PKCE S256 required, so the provider refuses its code exchange without a verifier;
- the client scope `reports:read` (stretch), optional for `notes-app`;
- one test user, `demo-user`.

The three secrets in it are `${...}` placeholders that Keycloak fills from its environment (Compose passes them from `.env`); no credential is stored in the file.

## Done when: the lesson's checklist and the proof for each line

| # | Done when (from the lesson) | Command | What proves it |
| --- | --- | --- | --- |
| 1 | The provider's discovery document and keys are reachable, and your app's registration lists one exact redirect URI. | `make up` (prints the discovery document and the key count), `make test-integration` | `make up` waits for the provider and prints `issuer`, `authorization_endpoint`, `jwks_uri` and the number of signing keys. [`test_provider_setup.py`](tests/integration/test_provider_setup.py) reads the registration through the provider's admin API: the client `notes-app` is confidential, standard flow only, no password grant, PKCE S256, and `redirectUris` is exactly `["http://localhost:3000/callback"]`. |
| 2 | A full sign-in works, and the token exchange happens server-side, never in the browser. | `make demo` (steps 2 to 4), `make test-integration`, `make test-e2e` | [`test_code_flow.py`](tests/integration/test_code_flow.py): the authorization request carries `response_type=code`, an S256 challenge, `state`, `nonce` and the exact redirect URI, and no secret or verifier; the user authenticates at the provider; the callback creates a session. The test records the app's own HTTP client: exactly one POST to the token endpoint, carrying the verifier and the client secret, made by the server. No access, refresh or ID token appears in any URL, header or page the browser received. [`test_server.py`](tests/e2e/test_server.py) does the same flow against a real gunicorn process. |
| 3 | The validator rejects a wrong-audience token, an expired token and a wrong-key token, each with a clear reason. | `make demo` (step 5), `make check`, `make test-integration` | `make demo` takes the real ID token from the session and shows: wrong audience -> `audience claim does not match client id`; expired -> `token has expired`; wrong key -> `signature verification failed`; `alg: none` -> `signing algorithm 'none' is not accepted`; wrong nonce -> `nonce mismatch: possible token substitution`. The same checks, plus issuer, authorized party, issued-at, `at_hash`, algorithm confusion and key rotation, are unit tests in [`test_claims.py`](tests/unit/test_claims.py) and [`test_jwks_verifier.py`](tests/unit/test_jwks_verifier.py). |
| 4 | A mismatched `state`, a lookalike redirect URI and a reused code are each refused, and your notes say which attack each protection prevents. | `make demo` (steps 9 to 14), `make test-integration` | [`test_flow_protections.py`](tests/integration/test_flow_protections.py): a changed state -> 400 and no session; the attacker's valid code and state completed in another browser -> 400 (login CSRF); a replayed callback -> 400; three lookalike redirect URIs -> the provider answers 400 and never redirects; a code exchanged twice -> `invalid_grant`; the wrong PKCE verifier -> `invalid_grant`. The table "The attacks the protections prevent" above is the notes. |
| 5 | The browser holds only an opaque session cookie with secure flags, and a refresh issues a new refresh token and invalidates the old one. | `make demo` (steps 4, 6, 7), `make test-integration` | [`test_session_lifecycle.py`](tests/integration/test_session_lifecycle.py): `__Host-session`, `HttpOnly`, `Secure`, `SameSite=Lax`, no dot in the value (not a JWT); `/me` returns the identity and the scopes, never a token; `POST /refresh` (CSRF token required) changes the refresh token held on the server and the provider answers `invalid_grant` to the old one. |
| 6 | After sign-out, the old session and the old refresh token are both rejected. | `make demo` (step 8), `make test-integration` | `POST /logout` (CSRF token required) deletes the session and calls the revocation endpoint; the old cookie then gets 401, and the provider answers `invalid_grant` to the refresh token. |

### The scenario, as `make demo` runs it

The app runs in-process over the Flask test client (the same app and adapters as in production), so the demo can show what only the server sees: the tokens it holds and the refresh token before and after rotation.

```text
$ make demo
 1. PASS  the provider's discovery document and signing keys are reachable
        issuer http://localhost:8180/realms/demo; 2 signing keys at http://localhost:8180/realms/demo/protocol/openid-connect/certs
 2. PASS  the app sends the browser to the provider with state, nonce and an S256 challenge
        redirect to /realms/demo/protocol/openid-connect/auth: response_type=code, S256 challenge, state, nonce, exact redirect_uri, no client secret in the URL, no verifier in the URL, attempt coo...
 3. PASS  the user authenticates at the provider and is redirected to the one registered URI
        provider answered 302, redirect to /callback with code and the same state
 4. PASS  the code is exchanged on the server and the browser gets only an opaque session cookie
        callback -> 302; cookie __Host-session=<43 opaque characters> (Expires=Tue, 27 Oct 2026 15:20:21 GMT; Max-Age=28800; Secure; HttpOnly; Path=/; SameSite=Lax); server holds access, refresh an...
 5. PASS  the ID token validator rejects five bad tokens, each for its own reason
        wrong audience -> audience claim does not match client id; expired -> token has expired; wrong key -> signature verification failed; none algorithm -> signing algorithm 'none' is not accept...
 6. PASS  the session shows who signed in, never a token, and the server calls the provider for the browser
        /me -> ['scopes', 'session_expires_at', 'subject', 'username']; /api/profile -> 200 {'email': 'demo-user@example.test', 'subject': '440e8d04-3a4f-4f55-af6f-310424195f5d', 'username': 'demo-...
 7. PASS  a refresh rotates the refresh token and the old one is refused
        POST /refresh -> 200; refresh token changed: True; old token at the provider: invalid_grant
 8. PASS  after sign-out the old session and the old refresh token are both refused
        POST /logout -> 303; old cookie -> 401; refresh token at the provider: invalid_grant
 9. PASS  a callback with a mismatched state is refused
        GET /callback with a changed state -> 400
10. PASS  a callback from a browser that did not start the login is refused
        the attacker's own code and state in another browser -> 400
11. PASS  a callback cannot be replayed
        first use -> 302, replay -> 400
12. PASS  a lookalike redirect URI is refused by the provider itself
        localhost:3000/callback.evil.example.test -> 400, no redirect; localhost:3000/callback/ -> 400, no redirect; localhost.evil.example.test:3000/callback -> 400, no redirect
13. PASS  a code cannot be exchanged a second time
        second exchange: invalid_grant (Code not valid)
14. PASS  a stolen code is useless without the PKCE verifier
        exchange with another verifier: invalid_grant (PKCE verification failed: Code mismatch)
15. PASS  a route that needs the reports:read scope refuses a sign-in without it
        /reports without the scope -> 403, with it -> 200
16. PASS  a public client (no secret) cannot exchange a code without the PKCE verifier
        without a verifier -> 400 (PKCE code verifier not specified); with it -> 200
16 of 16 checks passed
```

## The attacks the protections prevent

| Protection | Refuses | Attack it prevents |
| --- | --- | --- |
| `state` plus a login-attempt cookie, single use | a callback with the wrong state, from a browser that did not start the login, or replayed | login CSRF: an attacker's own code and state completed in a victim's browser would sign the victim into the attacker's account |
| Exact-match redirect URI at the provider | `http://localhost:3000/callback.evil.example.test`, a trailing slash, a lookalike host | the authorization code being delivered to a page the attacker controls |
| One-time authorization code | a second exchange of the same code (`invalid_grant`) | replay of a code that leaked through a log, a proxy or a browser history |
| PKCE (S256 challenge, server-held verifier) | an exchange with another verifier (`invalid_grant`) | a code intercepted in transit being redeemed by someone other than the party that started the login |
| Signature check against the provider's keys, algorithm allow-list | a token signed by another key, `alg: none`, an HMAC token keyed with the public key | a forged token |
| `iss`, `aud`, `azp`, `exp`, `iat` | a token from another provider, for another client, or expired | a genuine token that was never meant for this app, or that is too old |
| `nonce` | a token from another login attempt | token substitution, which `state` alone does not cover |
| Server-side session, opaque cookie, tokens never sent to the browser | nothing to steal from the page | one XSS bug anywhere becoming a stolen token |
| Refresh-token rotation | the previous refresh token (`invalid_grant`) | a leaked refresh token living forever |
| Sign-out with revocation | the refresh token after sign-out (`invalid_grant`) | a refresh token that outlives the session it came from |

## Stretch goals

| Stretch (from the lesson) | Built? |
| --- | --- |
| Add a second client as a public single-page app and explain why it must also use PKCE and keep no secret. | Yes, as a client registration: `notes-spa` is public and has no secret, so the only thing binding a code to the party that asked for it is PKCE; `make demo` and `test_a_public_client_cannot_exchange_a_code_without_the_pkce_verifier` show the provider refusing its exchange without a verifier and accepting it with one. There is no single-page app code. |
| Add role or scope checks so one route needs an elevated scope, and test the refusal. | Yes. `GET /reports` needs `reports:read`; a default sign-in gets 403, `/login?scope=reports:read` gets 200. Extra scopes are taken only from an allow-list (`OIDC_ALLOWED_EXTRA_SCOPES`). |
| Sender-constrain the tokens and explain what replay risk that removes. | No. A stolen access token is usable until it expires (two minutes here); DPoP or mutual TLS would bind it to the client's key. Described in [ARCHITECTURE.md](ARCHITECTURE.md), "How to extend it". |

## What is simplified for teaching

Only what the lesson scopes out, plus where this build differs from the lesson's text:

- Keycloak runs in development mode (embedded database, HTTP). A production provider runs `start` with PostgreSQL, TLS and a hostname.
- Sessions and pending logins are in the memory of one process (one gunicorn worker, eight threads); a restart signs everyone out. Redis behind the two store ports is the way to scale out.
- Sign-out does not end the provider's own browser session (no RP-initiated logout), so the next `/login` can sign in without a password prompt while that session lasts.
- The lesson's sample looks the pending login up by `state` alone and uses `python-jose`; this build binds the callback to the browser with a cookie ([ADR 1](docs/adr/0001-bind-the-callback-to-the-browser.md)) and uses PyJWT with an algorithm allow-list ([ADR 2](docs/adr/0002-verify-signatures-against-an-allow-list.md)).
- Keycloak runs on port 8180, not the lesson's 8080, because 8080 is commonly taken; `OIDC_ISSUER` and `KEYCLOAK_PORT` change it.

## Project structure

```text
src/oidc_login/
  domain/            PKCE, ID token claim checks, scope rules, value objects, named errors with reasons.
                     Depends on nothing outside the standard library.
  application/       LoginService (start, complete, resolve, refresh, sign out) and its ports.
                     Depends on domain only.
  infrastructure/    OidcProvider (httpx), JwksTokenVerifier (PyJWT), in-memory stores, settings, JSON logging,
                     the clock. Depends on application and domain.
  interfaces/        the Flask app, cookies and headers, the composition root, WSGI and gunicorn wiring, the health
                     program, the scripted browser and the demo. Nothing depends on it.
idp/                 realm-demo.json: the provider's whole configuration.
tests/
  unit/              domain, application with a fake provider that enforces PKCE, single-use codes and rotation,
                     the verifier, the provider adapter over a mock transport, the HTTP layer. No provider.
  integration/       token validation, flow protections, session lifecycle, stretch goals, against Keycloak.
  e2e/               a real gunicorn process, a scripted browser and Keycloak.
tech/                one note per technology, from zero, with an index (tech/README.md).
docs/adr/            decision records: callback binding, signature allow-list, tokens on the server.
docker-compose.yml   Keycloak 26.4, and the app under the `app` profile.     Dockerfile  the app as an image.
pyproject.toml       metadata and every tool's configuration (ruff, mypy, pytest, import-linter).
requirements*.lock   hash-pinned dependencies (runtime, and runtime plus development tools).
Makefile             the only commands a reader needs (make help).
```

The dependency rule (domain depends on nothing; application on domain; infrastructure and interfaces on both; nothing on interfaces) is enforced by `make lint` through import-linter. A second contract keeps Flask, werkzeug, httpx, the JWT library and cryptography out of `domain` and `application`.

## Author and license

Written by Sumit Srivastava. Released under the MIT License, see [LICENSE](LICENSE). Changes are in [CHANGELOG.md](CHANGELOG.md).
