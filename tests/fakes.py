"""Stand-ins for the ports, faithful enough to exercise the flow without a provider: a signing key that mints ID
tokens, a provider that enforces PKCE, single-use codes and refresh-token rotation, and a hand-moved clock."""

from __future__ import annotations

import base64
import hashlib
import itertools
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from oidc_login.domain.errors import ProviderError, ProviderUnavailableError
from oidc_login.domain.models import ProviderMetadata, TokenResponse

ISSUER = "http://localhost:8080/realms/demo"
CLIENT_ID = "notes-app"
REDIRECT_URI = "http://localhost:3000/callback"
START = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime = START) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


class CountingTokens:
    """Predictable random values: t1, t2, ... (64-byte requests give a valid 43+ character PKCE verifier)."""

    def __init__(self) -> None:
        self._count = itertools.count(1)

    def token(self, nbytes: int = 32) -> str:
        number = next(self._count)
        return f"t{number}-" + "x" * max(nbytes - len(str(number)) - 2, 40 if nbytes >= 64 else 8)


class Signer:
    """An RSA key pair, its JWKS, and a way to mint tokens signed with it."""

    def __init__(self, kid: str = "key-1") -> None:
        self.kid = kid
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, Any]:
        public = RSAAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def mint(self, claims: dict[str, Any], *, algorithm: str = "RS256", headers: dict[str, Any] | None = None) -> str:
        return jwt.encode(claims, self.private_key, algorithm=algorithm, headers={"kid": self.kid, **(headers or {})})


def id_token_claims(clock: FakeClock, *, nonce: str, subject: str = "user-1", **overrides: Any) -> dict[str, Any]:
    """Claims a well-behaved provider puts in an ID token for this app."""
    now = int(clock.now().timestamp())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": subject,
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
        "preferred_username": "demo-user",
        "email": "demo-user@example.test",
    }
    claims.update(overrides)
    return claims


def access_token_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode()).digest()
    return base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode()


class FakeVerifier:
    """Verifier port backed by the same Signer, using the real verification class."""

    def __init__(self, signer: Signer) -> None:
        from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier

        self._inner = JwksTokenVerifier(signer.jwks, monotonic=time.monotonic)

    def verify(self, id_token: str) -> dict[str, Any]:
        return self._inner.verify(id_token)


class FakeProvider:
    """An in-memory identity provider that behaves like the real one where it matters to the flow."""

    def __init__(self, signer: Signer, clock: FakeClock) -> None:
        self.signer = signer
        self.clock = clock
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.codes: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, bool] = {}  # token -> still valid
        self._counter = itertools.count(1)
        self.last_authorization: dict[str, str] = {}
        self.id_token_overrides: dict[str, Any] = {}
        self.id_token_signer: Signer | None = None
        self.id_token_factory: Callable[[str, str], str] | None = None  # (nonce, access token) -> raw token
        self.omit_id_token = False
        self.unavailable = False
        self.access_lifetime = 120
        self.granted_scope = "openid profile email"

    def metadata(self) -> ProviderMetadata:
        if self.unavailable:
            raise ProviderUnavailableError("down")
        return ProviderMetadata(
            ISSUER, f"{ISSUER}/auth", f"{ISSUER}/token", f"{ISSUER}/certs", f"{ISSUER}/userinfo", f"{ISSUER}/revoke"
        )

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str, scope: str) -> str:
        self.last_authorization = {"state": state, "nonce": nonce, "code_challenge": code_challenge, "scope": scope}
        return f"{ISSUER}/auth?state={state}&nonce={nonce}&code_challenge={code_challenge}&scope={scope}"

    def issue_code(self) -> str:
        """What the provider does after the user signs in: a one-time code bound to the challenge and nonce."""
        code = f"code-{next(self._counter)}"
        self.codes[code] = dict(self.last_authorization)
        return code

    def exchange_code(self, *, code: str, code_verifier: str) -> TokenResponse:
        self.requests.append(("exchange", {"code": code, "code_verifier": code_verifier}))
        grant = self.codes.pop(code, None)  # single use
        if grant is None:
            raise ProviderError("invalid_grant", "Code not valid")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        if challenge != grant["code_challenge"]:
            raise ProviderError("invalid_grant", "PKCE verification failed")
        return self._tokens(grant["nonce"], grant["scope"], with_id_token=True)

    def refresh(self, refresh_token: str) -> TokenResponse:
        self.requests.append(("refresh", {"refresh_token": refresh_token}))
        if not self.refresh_tokens.get(refresh_token):
            raise ProviderError("invalid_grant", "Token is not active")
        self.refresh_tokens[refresh_token] = False  # rotation: the old one stops working
        return self._tokens("", self.granted_scope, with_id_token=False)

    def revoke(self, refresh_token: str) -> None:
        self.requests.append(("revoke", {"refresh_token": refresh_token}))
        self.refresh_tokens[refresh_token] = False

    def userinfo(self, access_token: str) -> dict[str, Any]:
        self.requests.append(("userinfo", {"access_token": access_token}))
        return {"sub": "user-1", "preferred_username": "demo-user", "email": "demo-user@example.test"}

    def _tokens(self, nonce: str, scope: str, *, with_id_token: bool) -> TokenResponse:
        number = next(self._counter)
        access, refresh = f"access-{number}", f"refresh-{number}"
        self.refresh_tokens[refresh] = True
        id_token = None
        if with_id_token and self.id_token_factory is not None:
            id_token = self.id_token_factory(nonce, access)
        elif with_id_token and not self.omit_id_token:
            claims = id_token_claims(self.clock, nonce=nonce, at_hash=access_token_hash(access))
            claims.update(self.id_token_overrides)
            id_token = (self.id_token_signer or self.signer).mint({k: v for k, v in claims.items() if v is not None})
        return TokenResponse(access, refresh, id_token, self.access_lifetime, scope)
