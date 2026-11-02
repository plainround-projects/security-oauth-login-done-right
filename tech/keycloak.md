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

### Ideas you need first

- **An identity provider.** A service whose job is to know who people are and vouch for them to other applications, so each application does not keep its own passwords. Large companies run one; this repository runs Keycloak locally.
- **A realm, a client, a user.** In Keycloak a realm is one self-contained world; a client is an application registered in it; a user is a person with a password.
- **A container.** A running, isolated copy of a program packaged with everything it needs (`tech/docker.md`).
- **A placeholder.** `${NAME}` inside the realm file is replaced by the value of the environment variable `NAME` when Keycloak imports the file, so secrets stay out of the file.

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

### Line by line: `idp/realm-demo.json`

A Keycloak **realm** is one self-contained set of users, clients and settings. This JSON file describes the `demo` realm; Keycloak reads it at start-up (`--import-realm`) and creates everything in it. **JSON** is a text format of objects `{ "name": value }`, lists `[ ... ]`, texts, numbers and `true`/`false` (`tech/json.md`). A text like `${NAME}` is a **placeholder**: Keycloak replaces it with the value of that environment variable when it imports the file, so no secret is stored in the file. The meaning of each key below is from Keycloak's realm representation; the import and placeholder behaviour was checked against its documentation.

```json
{
  "realm": "demo",
```

The object starts. `"realm": "demo"` is the realm's name; it is part of every address (`/realms/demo/...`) and of the issuer.

```json
  "displayName": "Plainround demo realm",
  "enabled": true,
```

`displayName` is the human-readable name; `enabled: true` turns the realm on.

```json
  "sslRequired": "external",
```

`sslRequired: "external"` means HTTPS is required for requests that come from outside the local machine or private networks; plain HTTP is allowed from `localhost`, which is what the demo uses.

```json
  "registrationAllowed": false,
  "resetPasswordAllowed": false,
  "rememberMe": false,
  "loginWithEmailAllowed": false,
  "duplicateEmailsAllowed": false,
```

Four self-service features switched off: nobody can register themselves (`registrationAllowed`), reset a password by email (`resetPasswordAllowed`), stay signed in with "remember me" (`rememberMe`) or sign in by email address instead of username (`loginWithEmailAllowed`); two users cannot share an email (`duplicateEmailsAllowed: false`).

```json
  "bruteForceProtected": true,
  "failureFactor": 10,
```

`bruteForceProtected: true` makes Keycloak temporarily lock an account after repeated wrong passwords; `failureFactor: 10` is the number of failures that triggers it.

```json
  "accessTokenLifespan": 120,
```

`accessTokenLifespan: 120`: an access token is valid for 120 seconds. Short lifetimes limit the damage of a stolen token; the app refreshes it when needed.

```json
  "ssoSessionIdleTimeout": 1800,
  "ssoSessionMaxLifespan": 28800,
```

`ssoSessionIdleTimeout: 1800` ends the provider's own session after 30 minutes idle; `ssoSessionMaxLifespan: 28800` ends it after 8 hours whatever happens. These bound how long a refresh token can keep working.

```json
  "accessCodeLifespan": 60,
```

`accessCodeLifespan: 60`: the one-time authorization code must be exchanged within 60 seconds.

```json
  "revokeRefreshToken": true,
  "refreshTokenMaxReuse": 0,
```

`revokeRefreshToken: true` with `refreshTokenMaxReuse: 0` turns on refresh token rotation: each refresh token can be used exactly once, and using an old one again fails with `invalid_grant`.

```json
  "defaultSignatureAlgorithm": "RS256",
```

`defaultSignatureAlgorithm: "RS256"`: tokens are signed with an RSA key and SHA-256, the algorithm on the app's allow-list.

```json
  "clientScopes": [
```

`clientScopes` is the list of scopes this realm defines. A **client scope** is a named bundle that decides which claims are added to tokens when a client asks for that scope.

```json
    {
      "name": "profile",
      "description": "The user's name, as claims in the ID token and userinfo",
      "protocol": "openid-connect",
      "attributes": {
        "include.in.token.scope": "true",
        "display.on.consent.screen": "false"
      },
```

The first scope is `profile`: a description, the protocol `openid-connect`, and attributes: `include.in.token.scope` puts the scope name in the token's `scope` claim and `display.on.consent.screen: false` hides it from a consent page.

```json
      "protocolMappers": [
        {
          "name": "username",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-usermodel-property-mapper",
          "consentRequired": false,
          "config": {
            "user.attribute": "username",
            "claim.name": "preferred_username",
            "jsonType.label": "String",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true"
          }
        },
```

`protocolMappers` say how to fill claims. The first mapper, `username`, is of the type `oidc-usermodel-property-mapper`: it copies a property of the user into a claim. `user.attribute: username` is the source and `claim.name: preferred_username` the claim; `jsonType.label: String` makes it text; and the three `... .claim` switches put the claim in the ID token, the access token and the userinfo answer.

```json
        {
          "name": "given name",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-usermodel-property-mapper",
          "consentRequired": false,
          "config": {
            "user.attribute": "firstName",
            "claim.name": "given_name",
            "jsonType.label": "String",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true"
          }
        },
```

The second mapper copies the user's first name into the claim `given_name`, in all three places.

```json
        {
          "name": "family name",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-usermodel-property-mapper",
          "consentRequired": false,
          "config": {
            "user.attribute": "lastName",
            "claim.name": "family_name",
            "jsonType.label": "String",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true"
          }
        }
      ]
    },
```

The third copies the last name into `family_name`; the `]` and `}` close the mapper list and the scope.

```json
    {
      "name": "email",
      "description": "The user's email address, as claims in the ID token and userinfo",
      "protocol": "openid-connect",
      "attributes": {
        "include.in.token.scope": "true",
        "display.on.consent.screen": "false"
      },
```

The scope `email` has the same attributes.

```json
      "protocolMappers": [
        {
          "name": "email",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-usermodel-property-mapper",
          "consentRequired": false,
          "config": {
            "user.attribute": "email",
            "claim.name": "email",
            "jsonType.label": "String",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true"
          }
        }
      ]
    },
```

Its mapper copies the user's `email` property into the claim `email` in the ID token, access token and userinfo; the brackets close the scope.

```json
    {
      "name": "reports:read",
      "description": "Read the sample reports (the elevated scope the /reports route needs)",
      "protocol": "openid-connect",
      "attributes": {
        "include.in.token.scope": "true",
        "display.on.consent.screen": "false"
      }
    }
```

The scope `reports:read` is the elevated scope that the `/reports` route needs. It has no mapper because it changes nothing in the claims; its presence in the token's `scope` claim is the point.

```json
  ],
  "clients": [
```

The list of scopes ends and `clients` starts. A **client** is an application registered with the provider.

```json
    {
      "clientId": "notes-app",
      "name": "Notes app (confidential client)",
      "description": "The server-side app of this project: authorization code flow with PKCE, exactly one redirect URI.",
      "enabled": true,
      "protocol": "openid-connect",
```

The first client is `notes-app`, the server-side app: id, display name and description, enabled, using OpenID Connect.

```json
      "publicClient": false,
      "clientAuthenticatorType": "client-secret",
      "secret": "${NOTES_APP_CLIENT_SECRET}",
```

`publicClient: false` makes it a **confidential client** (it can keep a secret). `clientAuthenticatorType: "client-secret"` means it proves who it is with a secret; the secret is the placeholder `${NOTES_APP_CLIENT_SECRET}`.

```json
      "standardFlowEnabled": true,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
```

`standardFlowEnabled: true` allows the authorization code flow. The other three are off: `implicitFlowEnabled` (tokens in the address; insecure), `directAccessGrantsEnabled` (the password grant, where the app would see the user's password) and `serviceAccountsEnabled` (machine-to-machine sign-in).

```json
      "fullScopeAllowed": true,
```

`fullScopeAllowed: true` does not restrict which of the user's roles may go into tokens (this realm defines no roles).

```json
      "redirectUris": [
        "${APP_BASE_URL}/callback"
      ],
```

`redirectUris` has exactly one entry, `${APP_BASE_URL}/callback`, filled in at import. Keycloak compares the redirect address in a login request with this list exactly; no wildcard, so look-alike addresses are refused.

```json
      "webOrigins": [],
```

`webOrigins: []` allows no browser cross-origin requests.

```json
      "attributes": {
        "pkce.code.challenge.method": "S256",
        "post.logout.redirect.uris": "",
        "use.refresh.tokens": "true"
      },
```

`pkce.code.challenge.method: "S256"` makes PKCE with S256 mandatory for this client. `post.logout.redirect.uris` is empty (no post-logout redirect) and `use.refresh.tokens: "true"` allows refresh tokens.

```json
      "optionalClientScopes": [
        "reports:read"
      ],
```

`optionalClientScopes`: `reports:read` is granted only when the app asks for it.

```json
      "defaultClientScopes": [
        "profile",
        "email"
      ]
```

`defaultClientScopes`: `profile` and `email` are always included.

```json
    {
      "clientId": "notes-spa",
      "name": "Notes single-page app (public client, stretch goal)",
      "description": "A public client has no secret, so PKCE is what protects its code exchange; the provider refuses the exchange without a verifier.",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": true,
      "standardFlowEnabled": true,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
```

The second client, `notes-spa`, a stretch goal: a **public client** (`publicClient: true`, no secret, like a browser-only app), standard flow only, the other three off.

```json
      "redirectUris": [
        "http://localhost:3001/callback"
      ],
      "webOrigins": [
        "http://localhost:3001"
      ],
```

One exact redirect address, `http://localhost:3001/callback`, and one allowed web origin.

```json
      "attributes": {
        "pkce.code.challenge.method": "S256"
      }
    }
```

PKCE with S256 is mandatory. With no secret, PKCE is the only protection of its code exchange, and the provider refuses the exchange without a verifier.

```json
  ],
  "users": [
```

The clients end and `users` starts.

```json
    {
      "username": "demo-user",
      "enabled": true,
      "emailVerified": true,
      "email": "demo-user@example.test",
      "firstName": "Demo",
      "lastName": "User",
```

The one user: `demo-user`, enabled, email verified, with an email on the reserved `example.test` domain, a first and a last name.

```json
      "credentials": [
        {
          "type": "password",
          "value": "${DEMO_USER_PASSWORD}",
          "temporary": false
        }
      ]
```

`credentials`: a password whose value is the placeholder `${DEMO_USER_PASSWORD}` and `temporary: false` (the user is not forced to change it).

```json
    }
  ]
}
```

The closing brackets of the user list and of the file.

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
