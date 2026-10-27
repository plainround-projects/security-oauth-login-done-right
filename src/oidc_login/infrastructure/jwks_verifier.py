"""ID token signature verification against the provider's published keys (JWKS), with an algorithm allow-list."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import jwt
from jwt import PyJWK
from jwt.exceptions import InvalidSignatureError, InvalidTokenError
from jwt.types import Options

from oidc_login.domain.errors import SignatureInvalidError, UnsupportedAlgorithmError

_log = logging.getLogger("oidc_login.verifier")
# Only asymmetric algorithms, listed by name: "none" and the HMAC family are refused, which closes the
# algorithm-confusion attack in which the public key is used as an HMAC secret.
DEFAULT_ALGORITHMS = ("RS256",)
_NO_CLAIM_CHECKS: Options = {
    "verify_signature": True,
    "verify_exp": False,
    "verify_nbf": False,
    "verify_iat": False,
    "verify_aud": False,
    "verify_iss": False,
    "verify_sub": False,
    "verify_jti": False,
}


class JwksTokenVerifier:
    """Verifies the signature and algorithm of a JWT; claim checks belong to the domain.

    The key is chosen by the token's ``kid``. An unknown ``kid`` triggers one refetch of the key set (the provider
    may have rotated), at most once per ``min_refresh_seconds``, so a stream of forged tokens cannot make the app
    hammer the provider.
    """

    def __init__(
        self,
        fetch_jwks: Callable[[], Mapping[str, Any]],
        *,
        algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS,
        min_refresh_seconds: float = 30,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch_jwks
        self._algorithms = algorithms
        self._min_refresh = min_refresh_seconds
        self._monotonic = monotonic
        self._keys: dict[str, PyJWK] = {}
        self._last_fetch: float | None = None
        self._lock = threading.Lock()

    def verify(self, id_token: str) -> dict[str, Any]:
        """Return the claims of a token whose signature verifies against the provider's key for its ``kid``."""
        try:
            header = jwt.get_unverified_header(id_token)
        except InvalidTokenError as error:
            raise SignatureInvalidError("token is malformed") from error
        algorithm = header.get("alg")
        if not isinstance(algorithm, str) or algorithm not in self._algorithms:
            raise UnsupportedAlgorithmError(str(algorithm))
        key = self._key_for(header.get("kid"), algorithm)
        try:
            claims = jwt.decode(id_token, key.key, algorithms=[algorithm], options=_NO_CLAIM_CHECKS)
        except InvalidSignatureError as error:
            raise SignatureInvalidError() from error
        except InvalidTokenError as error:
            raise SignatureInvalidError("token is malformed") from error
        return dict(claims)

    def _key_for(self, kid: object, algorithm: str) -> PyJWK:
        if not isinstance(kid, str) or not kid:
            raise SignatureInvalidError("token names no signing key (kid)")
        with self._lock:
            key = self._keys.get(kid)
            if key is None and self._may_refetch():
                self._load(algorithm)
                key = self._keys.get(kid)
        if key is None:
            raise SignatureInvalidError("signature verification failed: signing key not found")
        return key

    def _may_refetch(self) -> bool:
        return self._last_fetch is None or self._monotonic() - self._last_fetch >= self._min_refresh

    def _load(self, algorithm: str) -> None:
        self._last_fetch = self._monotonic()
        document = self._fetch()
        keys: dict[str, PyJWK] = {}
        for entry in document.get("keys", []):
            if not isinstance(entry, dict) or entry.get("use", "sig") != "sig" or not isinstance(entry.get("kid"), str):
                continue
            if entry.get("alg", algorithm) != algorithm:
                continue
            try:
                keys[entry["kid"]] = PyJWK.from_dict(entry)
            except Exception:  # one malformed key must not hide the others
                _log.warning("ignoring an unusable key in the key set", extra={"kid": entry.get("kid")})
        self._keys = keys
