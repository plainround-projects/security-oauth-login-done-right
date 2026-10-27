"""Immutable value objects of the sign-in flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PendingLogin:
    """What the app remembers between sending the browser to the provider and the browser coming back.

    The verifier never leaves the server. The ``attempt_id`` is also stored in a short-lived cookie, which ties the
    callback to the browser that started the login.
    """

    attempt_id: str
    state: str
    nonce: str
    code_verifier: str = field(repr=False)
    scope: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TokenSet:
    """Tokens as the provider issued them. They live on the server only."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    id_token: str = field(repr=False)
    access_expires_at: datetime = field(compare=False)
    scope: str = ""


@dataclass(frozen=True, slots=True)
class Identity:
    """Who the ID token says signed in."""

    subject: str
    username: str
    email: str | None = None


@dataclass(frozen=True, slots=True)
class UserSession:
    """A signed-in session: the identity, the tokens (server side), the CSRF token and the lifetimes."""

    session_id_hash: str
    identity: Identity
    tokens: TokenSet = field(repr=False)
    csrf_token: str = field(repr=False)
    created_at: datetime = field(compare=False)
    last_seen_at: datetime = field(compare=False)
    expires_at: datetime = field(compare=False)

    @property
    def scopes(self) -> frozenset[str]:
        """The scopes the provider granted for this sign-in."""
        return frozenset(self.tokens.scope.split())


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """The parts of the provider's discovery document the app uses."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str
    revocation_endpoint: str


@dataclass(frozen=True, slots=True)
class TokenResponse:
    """A token endpoint response, before it is validated. A refresh response may omit the ID token."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    id_token: str | None = field(repr=False)
    expires_in: int
    scope: str
