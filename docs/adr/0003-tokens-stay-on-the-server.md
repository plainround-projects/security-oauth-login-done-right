# 3. Tokens stay on the server, in memory

Date: 2026-10-27. Status: accepted.

## Context

The access, refresh and ID tokens have to live somewhere between requests. Anything the browser can read is readable by every script on the page, so one XSS bug anywhere in the app would leak them. The choices on the server are memory, a database or a cache.

## Decision

The browser holds one opaque session cookie. The server stores the SHA-256 of the cookie value with the identity, the tokens and a CSRF token in an in-memory `SessionStore`. Pending logins are in memory too. The tokens are excluded from `repr` and the logging formatter redacts any field whose name looks like a token, code, secret or cookie.

## Alternatives

- **Tokens in a cookie or `localStorage`.** Readable from the browser.
- **A database table.** Durable across restarts and shareable between replicas, but puts live refresh tokens at rest; they would need encryption and a key to manage.
- **Redis.** The right answer for several replicas and a good extension, but one more container for a teaching build with one process.

## Consequences

- A restart signs everyone out, and the app runs one gunicorn worker with eight threads. `ARCHITECTURE.md` lists this under limits and names the Redis adapter as the extension; the two stores are narrow ports.
- Concurrent refreshes of one session are serialized by a lock, because a rotating refresh token used twice is revoked by the provider.
- Idle and absolute limits are enforced by the application as well as by the provider's own session settings.
