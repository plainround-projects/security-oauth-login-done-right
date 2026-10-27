# 1. Bind the callback to the browser that started the login

Date: 2026-10-27. Status: accepted.

## Context

The lesson's sample keeps pending logins in a dictionary keyed by `state` and pops one when the callback arrives. That detects a wrong or reused `state`. It does not detect a login started in a different browser: an attacker starts a login in their own browser, authenticates as themselves, and sends the victim a link to `/callback?code=...&state=...`. The server finds the pending entry under that `state` and signs the victim's browser into the attacker's account (login CSRF). The OAuth security guidance requires the client to tie `state` to the user agent.

## Decision

`start` returns an attempt id as well as the `state`. The id goes in a `__Host-login` cookie (`HttpOnly`, `Secure`, `SameSite=Lax`, ten minutes) and the pending login is stored under it. The callback needs the cookie and a `state` that matches the stored one. The attempt is removed when it is read, so it can be used once.

## Alternatives

- **Sign the state and put the binding inside it.** Still needs a browser-held value to bind to, so it is the same cookie with more machinery.
- **Rely on `SameSite=Strict` for the session cookie.** It does not apply: at the callback there is no session yet.

## Consequences

- A callback in a browser without the cookie is a 400 and never reaches the provider. `unit/test_http_app.py` and `integration/test_flow_protections.py` show both cases.
- `SameSite=Lax` is required, not Strict: the callback is a cross-site top-level navigation from the provider, and only Lax cookies travel on it.
- Cookie-less clients (some embedded webviews) cannot complete a login. That is the intended failure.
