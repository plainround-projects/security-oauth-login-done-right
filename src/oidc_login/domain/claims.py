"""The checks on an ID token's claims (OpenID Connect Core, section 3.1.3.7), run after the signature is verified.

Each check raises its own named error, so a rejected token says which check failed. The signature itself is checked
first, by the ``TokenVerifier`` port: every claim below is meaningless on a token that could have been forged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from oidc_login.domain.errors import (
    AudienceMismatchError,
    AuthorizedPartyMismatchError,
    IssuerMismatchError,
    MissingClaimError,
    NonceMismatchError,
    TokenExpiredError,
    TokenNotYetValidError,
    TokenValidationError,
)
from oidc_login.domain.models import Identity


@dataclass(frozen=True, slots=True)
class Expectations:
    """What this particular login attempt expects to find in the token."""

    issuer: str
    client_id: str
    nonce: str
    now: datetime
    leeway: timedelta = timedelta(seconds=30)


def _timestamp(claims: Mapping[str, Any], name: str) -> datetime | None:
    value = claims.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MissingClaimError(name)
    return datetime.fromtimestamp(value, UTC)


def _audiences(claims: Mapping[str, Any]) -> list[str]:
    value = claims.get("aud")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise MissingClaimError("aud")


def check_id_token_claims(claims: Mapping[str, Any], expected: Expectations) -> Identity:
    """Return the identity in the token, or raise the error of the first check that fails.

    Order: issuer, audience (and authorized party when there are several audiences), expiry, issued-at, nonce,
    subject. All comparisons are exact; none is a prefix or pattern match.
    """
    if claims.get("iss") != expected.issuer:
        raise IssuerMismatchError
    audiences = _audiences(claims)
    if expected.client_id not in audiences:
        raise AudienceMismatchError
    if len(audiences) > 1 and claims.get("azp") != expected.client_id:
        raise AuthorizedPartyMismatchError
    expires_at = _timestamp(claims, "exp")
    if expires_at is None:
        raise MissingClaimError("exp")
    if expected.now >= expires_at + expected.leeway:
        raise TokenExpiredError
    issued_at = _timestamp(claims, "iat")
    if issued_at is not None and issued_at - expected.leeway > expected.now:
        raise TokenNotYetValidError
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not hmac.compare_digest(nonce.encode(), expected.nonce.encode()):
        raise NonceMismatchError
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise MissingClaimError("sub")
    username = claims.get("preferred_username")
    email = claims.get("email")
    return Identity(
        subject=subject,
        username=username if isinstance(username, str) and username else subject,
        email=email if isinstance(email, str) else None,
    )


def check_access_token_hash(claims: Mapping[str, Any], access_token: str) -> None:
    """If the ID token carries ``at_hash``, the access token delivered with it must match (OpenID Connect Core,
    section 3.1.3.8): the left half of the SHA-256 of the access token, base64url encoded. Absent is allowed."""
    expected = claims.get("at_hash")
    if expected is None:
        return
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    actual = base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode("ascii")
    if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), actual.encode()):
        raise TokenValidationError("access token hash does not match the ID token")
