# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Drawn architecture and flow figures in `docs/diagrams/`, light and dark, shown in the README.

## [0.1.0] - 2026-10-27

### Added

- Sign-in with an OpenID Connect provider (Keycloak 26 in a container, realm `demo` imported from `idp/realm-demo.json`): authorization code flow with PKCE (S256), a random `state` and `nonce`, the token exchange on the server, exactly one registered redirect URI.
- ID token validation: signature against the provider's JWKS with an algorithm allow-list, then issuer, audience, authorized party, expiry, issued-at, nonce, subject and `at_hash`, each failure with its own named error and reason.
- The callback bound to the browser that started the login (a `__Host-login` cookie), single-use login attempts, and a bounded pending store.
- Opaque server-side sessions in a `__Host-session` cookie, idle and absolute lifetimes, refresh with rotation under a lock, sign-out that revokes the refresh token at the provider.
- The lesson's stretch goals: a scope check on one route (`reports:read`), and a public client (`notes-spa`) that the provider refuses without a PKCE verifier.
- A scripted browser and `make demo`, which walk the flow and every protection against the live provider; integration tests per "Done when" line; an end-to-end test against a real gunicorn process and SIGTERM.
- Layered package with the dependency rule enforced by import-linter, unit tests with a fake provider that enforces PKCE, single-use codes and rotation, ruff (with security rules), mypy strict, hash-pinned lock files, a CycloneDX SBOM target, a non-root Dockerfile and a CI workflow with every action pinned to a commit.
