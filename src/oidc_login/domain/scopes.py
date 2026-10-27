"""OAuth scopes: parsing a request and checking that a grant covers what a route needs."""

from __future__ import annotations

from collections.abc import Iterable

from oidc_login.domain.errors import InsufficientScopeError

BASE_SCOPE = "openid profile email"


def requested_scope(extra: Iterable[str], allowed: frozenset[str]) -> str:
    """The base scopes (``openid`` for the ID token, ``profile`` and ``email`` for the claims the app shows) plus the
    extra scopes the caller asked for, each of which must be on the allow-list.

    Anything else is dropped rather than forwarded: a request parameter must not be able to widen what the app asks
    the provider for.
    """
    wanted = sorted({scope for scope in extra if scope in allowed})
    return " ".join([BASE_SCOPE, *wanted])


def require(granted: frozenset[str], needed: str) -> None:
    """Raise ``InsufficientScopeError`` unless the grant includes ``needed``."""
    if needed not in granted:
        raise InsufficientScopeError(needed)
