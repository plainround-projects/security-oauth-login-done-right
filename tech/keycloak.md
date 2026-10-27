# Keycloak 26.4

## What it is

Keycloak is an open-source **identity and access management server**. It stores users and their passwords, shows the login page, and speaks the standard protocols (OpenID Connect, OAuth 2.0, SAML) so other applications can let people sign in through it. In OAuth vocabulary it is the **authorization server** and the OpenID **provider**. It is a Java program that normally runs as its own container.

Its own terms: a **realm** is an isolated space with its own users, clients and settings (here, one realm named `demo`). A **client** is an application registered to use the realm. A **client scope** is a reusable bundle of "what this token contains" (claims) that a client can request. A **protocol mapper** copies a user attribute into a token claim.

## Why this repository uses it

The lesson needs a real provider so the protections are shown against real behavior: real redirects, real signed tokens, real refusal of a replayed code or a look-alike redirect URI. Running Keycloak locally costs nothing and needs no account. The tests and the demo are not simulations of the provider; they talk to it.

## Where it appears

| Path | What it does |
| --- | --- |
| `docker-compose.yml` | Runs `quay.io/keycloak/keycloak:26.4` in dev mode, imports the realm, exposes it on `127.0.0.1:8180` (`tech/docker-compose.md`). |
| `idp/realm-demo.json` | The whole realm as data: settings, scopes, two clients, one user (`tech/json.md`). |
| `Makefile` target `idp-check` | Fetches the discovery document and the signing keys (`tech/curl.md`). |
| `src/oidc_login/infrastructure/oidc_provider.py` | The client side of every call to Keycloak. |
| `tests/integration/`, `tests/e2e/` | Run against the live Keycloak. |

## How it works underneath

1. At start (`start-dev --import-realm`) Keycloak reads every `.json` file in `/opt/keycloak/data/import`. For each realm that does not exist yet, it creates it, replacing `${NAME}` placeholders from environment variables. If the realm already exists, the import is skipped.
2. In development mode Keycloak uses an embedded database and plain HTTP. State lives inside the container and disappears with `docker compose down -v`.
3. The realm publishes a **discovery document** at `/realms/demo/.well-known/openid-configuration` and its **signing keys** at `/realms/demo/protocol/openid-connect/certs`. The realm generates its RSA signing key on creation.
4. A browser login: the client redirects to `/realms/demo/protocol/openid-connect/auth`; Keycloak shows the login form; after authentication it redirects back with a code. The client trades the code at `/realms/demo/protocol/openid-connect/token`.
5. Management is on a separate **management port** (9000), which also serves `/health/ready` when `KC_HEALTH_ENABLED=true`.

## Walkthrough of this repository's use

The realm, key by key (all in `idp/realm-demo.json`):

```json
"realm": "demo",
"sslRequired": "external",
"registrationAllowed": false,
"resetPasswordAllowed": false,
"loginWithEmailAllowed": false,
"duplicateEmailsAllowed": false,
```
Realm `demo`. `sslRequired: external` means HTTPS is required for requests from outside private networks and not for `localhost`. No self-registration, no password-reset flow (nothing to attack that the lesson does not need), login by username only.

```json
"bruteForceProtected": true,
"failureFactor": 10,
```
Keycloak locks an account temporarily after 10 failed sign-ins.

```json
"accessTokenLifespan": 120,
"ssoSessionIdleTimeout": 1800,
"ssoSessionMaxLifespan": 28800,
"accessCodeLifespan": 60,
```
Access tokens last 120 seconds (short, so the refresh path is exercised and a stolen one dies quickly); the provider's own session idles out after 30 minutes and lives at most 8 hours; an authorization code is valid for 60 seconds.

```json
"revokeRefreshToken": true,
"refreshTokenMaxReuse": 0,
"defaultSignatureAlgorithm": "RS256",
```
**Refresh token rotation**: each use of a refresh token invalidates it and issues a new one; reuse is refused. And tokens are signed with RS256, matching the app's allow-list (`tech/jwt-and-jwks.md`).

```json
"clientScopes": [
  { "name": "profile", ..., "protocolMappers": [
      { "name": "username", "protocolMapper": "oidc-usermodel-property-mapper",
        "config": { "user.attribute": "username", "claim.name": "preferred_username",
                    "id.token.claim": "true", "access.token.claim": "true", "userinfo.token.claim": "true" } }, ... ] },
  { "name": "email", ... },
  { "name": "reports:read", "description": "Read the sample reports ..." }
]
```
Scopes are defined explicitly so the realm does not depend on Keycloak's built-in defaults. The `profile` scope maps the user's `username`, `firstName` and `lastName` to the claims `preferred_username`, `given_name` and `family_name`, in the ID token, the access token and the userinfo response. `email` maps the email. `reports:read` has no mappers; it exists so a client can request it and the app can check for it.

```json
"clientId": "notes-app",
"publicClient": false,
"clientAuthenticatorType": "client-secret",
"secret": "${NOTES_APP_CLIENT_SECRET}",
"standardFlowEnabled": true,
"implicitFlowEnabled": false,
"directAccessGrantsEnabled": false,
"serviceAccountsEnabled": false,
"redirectUris": ["${APP_BASE_URL}/callback"],
"attributes": { "pkce.code.challenge.method": "S256", "use.refresh.tokens": "true" },
"optionalClientScopes": ["reports:read"],
"defaultClientScopes": ["profile", "email"]
```
The app's registration: a **confidential** client that authenticates with a secret (the placeholder is filled from the environment, so the secret is never in git). Only the standard authorization-code flow is on: the implicit flow (tokens in URLs) and the password grant (`directAccessGrants`) are off. Exactly one redirect URI; anything else is refused before the app sees a request. PKCE with S256 is required. `profile` and `email` are given by default; `reports:read` only when the client asks for it with `scope=...`.

```json
"clientId": "notes-spa",
"publicClient": true,
"redirectUris": ["http://localhost:3001/callback"],
"attributes": { "pkce.code.challenge.method": "S256" }
```
A **public** client has no secret. This second client exists for the stretch goal in the demo that shows PKCE is the only protection of such a client's code exchange.

```json
"users": [{ "username": "demo-user", "enabled": true, "emailVerified": true,
            "email": "demo-user@example.test", "firstName": "Demo", "lastName": "User",
            "credentials": [{ "type": "password", "value": "${DEMO_USER_PASSWORD}", "temporary": false }] }]
```
One user. The password is a placeholder, filled from `DEMO_USER_PASSWORD` in `.env`.

### How the app talks to it

`OidcProvider` reads the discovery document once (with retries on transient failures), checks that its `issuer` equals the configured `OIDC_ISSUER`, and uses the endpoints it lists. The `/readyz` route of the app answers 503 when the provider is unreachable; `/healthz` stays 200, so a provider restart does not make the app look dead.

## Try it yourself

(Needs Docker and `make up`; Keycloak's first start can take minutes on a busy machine.)

1. Start it and verify the realm:
   ```bash
   make up
   ```
   Expect `keycloak` healthy and `idp-check` printing the issuer `http://localhost:8180/realms/demo`, the authorization endpoint, the `jwks_uri` and `signing keys` with a count (2 in the verified run).
2. Read the discovery document:
   ```bash
   curl -s http://localhost:8180/realms/demo/.well-known/openid-configuration | python3 -m json.tool | head -30
   ```
   Expect `issuer`, `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `userinfo_endpoint`, `revocation_endpoint`.
3. Look at the realm in the admin console: open `http://localhost:8180`, sign in as the admin from your `.env`, choose realm `demo`, then Clients > `notes-app`. Expect `Client authentication: On`, `Standard flow` on, `Implicit flow` off, one valid redirect URI.
4. Run the integration tests against it: `make test-integration`. Expect 22 passed.
5. Clean up: `make down`.

## Mistakes people make

- Using `start-dev` for anything real.
- Wildcard redirect URIs (`http://localhost:3000/*`). The realm has one exact URI.
- Leaving the implicit flow or direct password grants enabled.
- Committing the client secret in the realm file. Placeholders keep it out.
- Forgetting that an existing realm is not re-imported, then wondering why an edit to the JSON does nothing.
- Mixing hostnames (`localhost` vs the container name), which changes the token issuer. See `tech/docker-compose.md`.
- Long-lived access tokens "to avoid refreshing".

## Check yourself

1. What is a realm?
   *An isolated space of users, clients and settings; here `demo`.*
2. Why is the client secret `${NOTES_APP_CLIENT_SECRET}` in the file?
   *A placeholder replaced from the environment at import, so no secret is in git.*
3. What does `implicitFlowEnabled: false` do?
   *Turns off the flow that returns tokens in the redirect URL.*
4. What is the difference between `notes-app` and `notes-spa`?
   *The first is confidential (has a secret); the second is public (no secret, PKCE is its protection).*
5. What does `revokeRefreshToken: true` with `refreshTokenMaxReuse: 0` mean?
   *Every refresh token works once; reuse is refused.*

## Further reading

- Keycloak documentation: https://www.keycloak.org/documentation
- Importing a realm: https://www.keycloak.org/server/importExport
- Running in a container: https://www.keycloak.org/server/containers
- Securing applications (OIDC client settings): https://www.keycloak.org/docs/latest/server_admin/#_oidc_clients
