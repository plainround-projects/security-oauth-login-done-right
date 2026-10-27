"""The authorization code flow with PKCE, ID token validation, server-side sessions with refresh rotation, and sign-out
with revocation."""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from dataclasses import dataclass, replace
from datetime import timedelta

from oidc_login.application.ports import (
    Clock,
    IdentityProvider,
    PendingLoginStore,
    SessionStore,
    TokenGenerator,
    TokenVerifier,
)
from oidc_login.domain.claims import Expectations, check_access_token_hash, check_id_token_claims
from oidc_login.domain.errors import LoginError, ProviderError, SessionNotFoundError, StateMismatchError
from oidc_login.domain.models import PendingLogin, TokenResponse, TokenSet, UserSession
from oidc_login.domain.pkce import challenge_for
from oidc_login.domain.scopes import requested_scope

_log = logging.getLogger("oidc_login.flow")


@dataclass(frozen=True, slots=True)
class LoginConfig:
    """Everything the flow needs to know about this app and the provider."""

    issuer: str
    client_id: str
    allowed_extra_scopes: frozenset[str]
    pending_ttl_seconds: int = 600
    session_idle_seconds: int = 900
    session_absolute_seconds: int = 28800
    refresh_margin_seconds: int = 30
    clock_leeway_seconds: int = 30


@dataclass(frozen=True, slots=True)
class StartedLogin:
    """Where to send the browser, and the id that goes in the short-lived login-attempt cookie."""

    authorization_url: str
    attempt_id: str
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session and the raw cookie value, which exists on the server only at this moment."""

    raw_session_id: str
    session: UserSession
    max_age_seconds: int


def hash_session_id(raw_session_id: str) -> str:
    """The stored form of a session cookie value."""
    return hashlib.sha256(raw_session_id.encode()).hexdigest()


class LoginService:
    """Starts and completes sign-in, and manages the session afterwards. No HTTP and no HTTP client in here."""

    def __init__(
        self,
        provider: IdentityProvider,
        verifier: TokenVerifier,
        pending: PendingLoginStore,
        sessions: SessionStore,
        clock: Clock,
        tokens: TokenGenerator,
        config: LoginConfig,
    ) -> None:
        self._provider = provider
        self._verifier = verifier
        self._pending = pending
        self._sessions = sessions
        self._clock = clock
        self._tokens = tokens
        self._config = config
        # One refresh at a time: two concurrent refreshes with the same rotating token would burn it.
        # ponytail: a single lock is enough for one process; a shared store needs a per-session lock there.
        self._refresh_lock = threading.Lock()

    def start(self, extra_scopes: list[str]) -> StartedLogin:
        """Begin a login: fresh state, nonce and PKCE verifier; only the challenge goes to the provider."""
        verifier = self._tokens.token(64)
        pending = PendingLogin(
            attempt_id=self._tokens.token(),
            state=self._tokens.token(),
            nonce=self._tokens.token(),
            code_verifier=verifier,
            scope=requested_scope(extra_scopes, self._config.allowed_extra_scopes),
            created_at=self._clock.now(),
        )
        self._pending.put(pending)
        url = self._provider.authorization_url(
            state=pending.state, nonce=pending.nonce, code_challenge=challenge_for(verifier), scope=pending.scope
        )
        _log.info("login started", extra={"event": "login.started", "scope": pending.scope})
        return StartedLogin(url, pending.attempt_id, self._config.pending_ttl_seconds)

    def complete(self, *, attempt_id: str | None, state: str | None, code: str | None) -> IssuedSession:
        """Finish a login from the callback.

        Raises ``StateMismatchError`` unless the callback belongs to a login this browser started and has not
        finished yet; ``ProviderError`` when the provider refuses the code; ``TokenValidationError`` (a subclass
        per check) when the ID token is not acceptable.
        """
        pending = self._claim_attempt(attempt_id, state)
        if not code:
            raise StateMismatchError("the callback carries no authorization code")
        response = self._provider.exchange_code(code=code, code_verifier=pending.code_verifier)
        if response.id_token is None:
            raise ProviderError("invalid_response", "the token response has no ID token")
        claims = self._verifier.verify(response.id_token)
        now = self._clock.now()
        identity = check_id_token_claims(
            claims,
            Expectations(
                issuer=self._config.issuer,
                client_id=self._config.client_id,
                nonce=pending.nonce,
                now=now,
                leeway=timedelta(seconds=self._config.clock_leeway_seconds),
            ),
        )
        check_access_token_hash(claims, response.access_token)
        raw_session_id = self._tokens.token()
        session = UserSession(
            session_id_hash=hash_session_id(raw_session_id),
            identity=identity,
            tokens=self._token_set(response, previous=None),
            csrf_token=self._tokens.token(),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=self._config.session_absolute_seconds),
        )
        self._sessions.purge_inactive(now, timedelta(seconds=self._config.session_idle_seconds))
        self._sessions.add(session)
        _log.info("login completed", extra={"event": "login.completed", "subject": identity.subject})
        return IssuedSession(raw_session_id, session, self._config.session_absolute_seconds)

    def resolve(self, raw_session_id: str | None) -> UserSession | None:
        """The live session for a cookie value, or ``None`` when unknown, idle too long or past its lifetime."""
        if not raw_session_id:
            return None
        key = hash_session_id(raw_session_id)
        session = self._sessions.get(key)
        if session is None:
            return None
        now = self._clock.now()
        idle_limit = session.last_seen_at + timedelta(seconds=self._config.session_idle_seconds)
        if now >= session.expires_at or now >= idle_limit:
            self._sessions.delete(key)
            return None
        touched = replace(session, last_seen_at=now)
        self._sessions.replace(touched)
        return touched

    def refresh(self, session: UserSession) -> UserSession:
        """Rotate the tokens: the provider issues a new refresh token and the old one stops working.

        The session is dropped and the error raised when the provider refuses (the refresh token was revoked,
        reused or expired): the user has to sign in again.
        """
        with self._refresh_lock:
            current = self._sessions.get(session.session_id_hash)
            if current is None:
                raise SessionNotFoundError("session ended")
            refresh_token = current.tokens.refresh_token
            if refresh_token is None:
                raise SessionNotFoundError("session has no refresh token")
            try:
                response = self._provider.refresh(refresh_token)
            except LoginError:
                self._sessions.delete(current.session_id_hash)
                _log.warning("refresh refused, session dropped", extra={"event": "token.refresh_failed"})
                raise
            renewed = replace(current, tokens=self._token_set(response, previous=current.tokens))
            self._sessions.replace(renewed)
            _log.info("tokens refreshed", extra={"event": "token.refreshed", "subject": current.identity.subject})
            return renewed

    def access_token(self, session: UserSession) -> tuple[str, UserSession]:
        """An access token good for at least the refresh margin, refreshing first when it is about to expire."""
        margin = timedelta(seconds=self._config.refresh_margin_seconds)
        if self._clock.now() + margin >= session.tokens.access_expires_at:
            session = self.refresh(session)
        return session.tokens.access_token, session

    def sign_out(self, raw_session_id: str | None) -> bool:
        """End the session here, then revoke the refresh token at the provider. Returns whether the provider
        confirmed the revocation; the local session is gone either way."""
        if not raw_session_id:
            return False
        session = self._sessions.delete(hash_session_id(raw_session_id))
        if session is None or session.tokens.refresh_token is None:
            return False
        try:
            self._provider.revoke(session.tokens.refresh_token)
        except LoginError:
            _log.warning("revocation failed at sign out", extra={"event": "logout.revoke_failed"})
            return False
        _log.info("signed out", extra={"event": "logout", "subject": session.identity.subject, "revoked": True})
        return True

    @staticmethod
    def csrf_valid(session: UserSession, supplied: str | None) -> bool:
        """Constant-time comparison of the supplied CSRF token with the session's."""
        return supplied is not None and hmac.compare_digest(session.csrf_token.encode(), supplied.encode())

    def _claim_attempt(self, attempt_id: str | None, state: str | None) -> PendingLogin:
        if not attempt_id or not state:
            raise StateMismatchError("the callback is not tied to a login this browser started")
        pending = self._pending.pop(attempt_id)
        if pending is None:
            raise StateMismatchError("unknown or already used login attempt")
        if not hmac.compare_digest(pending.state.encode(), state.encode()):
            raise StateMismatchError("state does not match the login this browser started")
        if self._clock.now() >= pending.created_at + timedelta(seconds=self._config.pending_ttl_seconds):
            raise StateMismatchError("the login attempt expired")
        return pending

    def _token_set(self, response: TokenResponse, *, previous: TokenSet | None) -> TokenSet:
        return TokenSet(
            access_token=response.access_token,
            refresh_token=response.refresh_token or (previous.refresh_token if previous else None),
            id_token=response.id_token or (previous.id_token if previous else ""),
            access_expires_at=self._clock.now() + timedelta(seconds=response.expires_in),
            scope=response.scope or (previous.scope if previous else ""),
        )
