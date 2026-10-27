"""Named errors. Messages are the reasons the lesson asks for: each failure says what was actually wrong."""

from __future__ import annotations


class LoginError(Exception):
    """Base class of every error the sign-in flow raises on purpose."""


class TokenValidationError(LoginError):
    """An ID token failed a check. ``reason`` names the check; the other subclasses carry a fixed one."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SignatureInvalidError(TokenValidationError):
    """The signature does not verify against the provider's key."""

    def __init__(self, detail: str = "signature verification failed") -> None:
        super().__init__(detail)


class UnsupportedAlgorithmError(TokenValidationError):
    """The token names a signing algorithm the app does not accept (``none``, ``HS256`` and the like)."""

    def __init__(self, algorithm: str) -> None:
        super().__init__(f"signing algorithm {algorithm!r} is not accepted")
        self.algorithm = algorithm


class IssuerMismatchError(TokenValidationError):
    """``iss`` is not the provider this app signs in with."""

    def __init__(self) -> None:
        super().__init__("issuer claim does not match the provider")


class AudienceMismatchError(TokenValidationError):
    """``aud`` does not include this app's client id."""

    def __init__(self) -> None:
        super().__init__("audience claim does not match client id")


class AuthorizedPartyMismatchError(TokenValidationError):
    """``azp`` names another client."""

    def __init__(self) -> None:
        super().__init__("authorized party claim does not match client id")


class TokenExpiredError(TokenValidationError):
    """``exp`` has passed."""

    def __init__(self) -> None:
        super().__init__("token has expired")


class TokenNotYetValidError(TokenValidationError):
    """``iat`` or ``nbf`` is in the future beyond the allowed clock skew."""

    def __init__(self) -> None:
        super().__init__("token is not valid yet")


class NonceMismatchError(TokenValidationError):
    """``nonce`` is not the value this login attempt sent: possible token substitution."""

    def __init__(self) -> None:
        super().__init__("nonce mismatch: possible token substitution")


class MissingClaimError(TokenValidationError):
    """A required claim is absent."""

    def __init__(self, claim: str) -> None:
        super().__init__(f"required claim {claim!r} is missing")
        self.claim = claim


class StateMismatchError(LoginError):
    """The callback does not belong to a login this browser started (wrong, reused or missing ``state``, or no
    login-attempt cookie)."""


class ProviderError(LoginError):
    """The provider answered with an OAuth error. ``code`` is its ``error`` value, for example ``invalid_grant``."""

    def __init__(self, code: str, description: str = "") -> None:
        super().__init__(f"{code}: {description}" if description else code)
        self.code = code
        self.description = description


class ProviderUnavailableError(LoginError):
    """The provider could not be reached or answered with something unusable."""


class SessionNotFoundError(LoginError):
    """No live session for the cookie value (unknown, expired or signed out)."""


class InsufficientScopeError(LoginError):
    """The session was not granted a scope the route needs."""

    def __init__(self, scope: str) -> None:
        super().__init__(f"scope {scope!r} was not granted")
        self.scope = scope
