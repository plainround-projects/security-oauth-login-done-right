"""Ports: what the sign-in flow needs from the outside world. Adapters live in ``infrastructure``."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from oidc_login.domain.models import PendingLogin, ProviderMetadata, TokenResponse, UserSession


class IdentityProvider(Protocol):
    """The OpenID Connect provider, as the back channel and the redirect see it."""

    def metadata(self) -> ProviderMetadata:
        """The provider's discovery document, validated (its issuer is the configured one)."""

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str, scope: str) -> str:
        """Where to send the browser: code flow, S256 challenge, the one registered redirect URI."""

    def exchange_code(self, *, code: str, code_verifier: str) -> TokenResponse:
        """Trade the code and the PKCE verifier for tokens, server to server. Raises ``ProviderError``."""

    def refresh(self, refresh_token: str) -> TokenResponse:
        """Trade a refresh token for new tokens; the provider rotates the refresh token. Raises ``ProviderError``."""

    def revoke(self, refresh_token: str) -> None:
        """Ask the provider to invalidate a refresh token (RFC 7009)."""

    def userinfo(self, access_token: str) -> dict[str, Any]:
        """Call the provider's userinfo endpoint with an access token."""


class TokenVerifier(Protocol):
    """Checks an ID token's signature and algorithm against the provider's published keys."""

    def verify(self, id_token: str) -> dict[str, Any]:
        """Return the claims of a token whose signature verifies; raise ``SignatureInvalidError`` or
        ``UnsupportedAlgorithmError`` otherwise. Claim checks (issuer, audience, ...) happen in the domain."""


class PendingLoginStore(Protocol):
    """Logins that have been started and not yet completed."""

    def put(self, pending: PendingLogin) -> None:
        """Remember a login attempt."""

    def pop(self, attempt_id: str) -> PendingLogin | None:
        """Remove and return the attempt: single use, so a replayed callback finds nothing."""


class SessionStore(Protocol):
    """Signed-in sessions, keyed by the hash of the cookie value."""

    def add(self, session: UserSession) -> None:
        """Store a new session."""

    def get(self, session_id_hash: str) -> UserSession | None:
        """Fetch a session."""

    def replace(self, session: UserSession) -> None:
        """Overwrite a session (after a refresh or a touch)."""

    def delete(self, session_id_hash: str) -> UserSession | None:
        """Remove a session and return it, if it existed."""

    def count(self) -> int:
        """How many sessions are held."""

    def purge_inactive(self, now: datetime, idle: timedelta) -> int:
        """Drop sessions past their lifetime or idle longer than ``idle``; return how many."""


class Clock(Protocol):
    """Time, injected so tests are deterministic."""

    def now(self) -> datetime:
        """The current time, timezone-aware (UTC)."""


class TokenGenerator(Protocol):
    """Unguessable values: state, nonce, PKCE verifier, session ids."""

    def token(self, nbytes: int = 32) -> str:
        """A URL-safe random string from ``nbytes`` of entropy."""
