"""System clock and random source."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


class SystemClock:
    """The real time, in UTC."""

    def now(self) -> datetime:
        """The current UTC time."""
        return datetime.now(UTC)


class SecretsTokenGenerator:
    """Random values from the operating system's CSPRNG."""

    def token(self, nbytes: int = 32) -> str:
        """A URL-safe token; ``nbytes=64`` gives an 86-character PKCE verifier."""
        return secrets.token_urlsafe(nbytes)
