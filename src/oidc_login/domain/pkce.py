"""PKCE (RFC 7636): the challenge derived from a verifier, so a stolen authorization code is useless on its own."""

from __future__ import annotations

import base64
import hashlib
import re

_VERIFIER = re.compile(r"[A-Za-z0-9\-._~]{43,128}")


def is_valid_verifier(verifier: str) -> bool:
    """True for a verifier of 43 to 128 unreserved characters, as the RFC requires."""
    return _VERIFIER.fullmatch(verifier) is not None


def challenge_for(verifier: str) -> str:
    """``base64url(sha256(verifier))`` without padding: the S256 method, the only one this app uses."""
    if not is_valid_verifier(verifier):
        raise ValueError("code verifier must be 43 to 128 unreserved characters")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
