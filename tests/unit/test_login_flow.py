from datetime import timedelta

import jwt
import pytest

from oidc_login.application.login_flow import LoginConfig, LoginService, hash_session_id
from oidc_login.domain.errors import (
    AudienceMismatchError,
    NonceMismatchError,
    ProviderError,
    SessionNotFoundError,
    SignatureInvalidError,
    StateMismatchError,
    TokenExpiredError,
    TokenValidationError,
    UnsupportedAlgorithmError,
)
from oidc_login.domain.pkce import challenge_for
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
from tests.fakes import (
    CLIENT_ID,
    ISSUER,
    CountingTokens,
    FakeClock,
    FakeProvider,
    FakeVerifier,
    Signer,
    id_token_claims,
)

CONFIG = LoginConfig(
    issuer=ISSUER,
    client_id=CLIENT_ID,
    allowed_extra_scopes=frozenset({"reports:read"}),
    pending_ttl_seconds=600,
    session_idle_seconds=900,
    session_absolute_seconds=28800,
    refresh_margin_seconds=30,
)


@pytest.fixture
def world():
    clock, signer = FakeClock(), Signer()
    provider = FakeProvider(signer, clock)
    sessions = InMemorySessionStore()
    service = LoginService(
        provider, FakeVerifier(signer), InMemoryPendingLoginStore(clock, 600), sessions, clock, CountingTokens(), CONFIG
    )
    return service, provider, sessions, clock, signer


def begin(service, provider, extra=()):
    """Start a login and play the user: returns the attempt id, the state and a code from the provider."""
    started = service.start(list(extra))
    return started.attempt_id, provider.last_authorization["state"], provider.issue_code()


def test_start_sends_only_the_challenge_never_the_verifier(world):
    service, provider, *_ = world
    started = service.start([])
    sent = provider.last_authorization
    assert sent["code_challenge"]
    assert sent["state"] != sent["nonce"]
    assert started.max_age_seconds == 600
    verifier = next(iter(service._pending._items.values())).code_verifier
    assert challenge_for(verifier) == sent["code_challenge"]
    assert verifier not in started.authorization_url


def test_a_scope_outside_the_allow_list_is_not_requested(world):
    service, provider, *_ = world
    service.start(["admin", "reports:read"])
    assert provider.last_authorization["scope"] == "openid profile email reports:read"


def test_a_full_sign_in_creates_a_session_whose_tokens_stay_on_the_server(world):
    service, provider, sessions, *_ = world
    attempt, state, code = begin(service, provider)
    issued = service.complete(attempt_id=attempt, state=state, code=code)
    assert issued.max_age_seconds == 28800
    session = sessions.get(hash_session_id(issued.raw_session_id))
    assert session is not None
    assert session.identity.subject == "user-1"
    assert session.identity.username == "demo-user"
    assert session.tokens.access_token.startswith("access-")
    assert session.tokens.refresh_token.startswith("refresh-")
    assert issued.raw_session_id not in (
        session.tokens.access_token,
        session.tokens.refresh_token,
        session.tokens.id_token,
    )
    assert "access-" not in repr(session)
    assert "refresh-" not in repr(session)
    assert [name for name, _ in provider.requests] == ["exchange"]


@pytest.mark.parametrize(
    ("attempt", "state"),
    [(None, "s"), ("", "s"), ("a", None), ("a", ""), ("unknown-attempt", "whatever")],
)
def test_a_callback_not_tied_to_a_login_this_browser_started_is_refused_before_any_exchange(world, attempt, state):
    service, provider, *_ = world
    service.start([])
    with pytest.raises(StateMismatchError):
        service.complete(attempt_id=attempt, state=state, code="code")
    assert provider.requests == []


def test_a_mismatched_state_is_refused_and_burns_the_attempt(world):
    service, provider, *_ = world
    attempt, state, code = begin(service, provider)
    with pytest.raises(StateMismatchError, match="state does not match"):
        service.complete(attempt_id=attempt, state="attacker-chosen-state", code=code)
    with pytest.raises(StateMismatchError, match="unknown or already used"):
        service.complete(attempt_id=attempt, state=state, code=code)
    assert provider.requests == []


def test_a_callback_cannot_be_replayed_once_it_succeeded(world):
    service, provider, *_ = world
    attempt, state, code = begin(service, provider)
    service.complete(attempt_id=attempt, state=state, code=code)
    with pytest.raises(StateMismatchError, match="already used"):
        service.complete(attempt_id=attempt, state=state, code=code)


def test_a_login_attempt_expires(world):
    service, provider, _, clock, _ = world
    attempt, state, code = begin(service, provider)
    clock.advance(seconds=601)
    with pytest.raises(StateMismatchError):
        service.complete(attempt_id=attempt, state=state, code=code)


def test_a_callback_without_a_code_is_refused(world):
    service, provider, *_ = world
    attempt, state, _ = begin(service, provider)
    with pytest.raises(StateMismatchError, match="no authorization code"):
        service.complete(attempt_id=attempt, state=state, code=None)


def test_a_code_cannot_be_exchanged_twice(world):
    service, provider, *_ = world
    attempt, state, code = begin(service, provider)
    service.complete(attempt_id=attempt, state=state, code=code)
    attempt2 = service.start([]).attempt_id
    with pytest.raises(ProviderError) as refused:
        service.complete(attempt_id=attempt2, state=provider.last_authorization["state"], code=code)
    assert refused.value.code == "invalid_grant"


def test_the_wrong_pkce_verifier_is_refused_by_the_provider(world):
    service, provider, *_ = world
    service.start([])
    code = provider.issue_code()
    with pytest.raises(ProviderError, match="PKCE verification failed"):
        provider.exchange_code(code=code, code_verifier="v" * 64)


@pytest.mark.parametrize(
    ("setup", "error", "reason"),
    [
        (
            lambda p: p.id_token_overrides.update(aud="another-client"),
            AudienceMismatchError,
            "audience claim does not match client id",
        ),
        (lambda p: p.id_token_overrides.update(exp=1), TokenExpiredError, "token has expired"),
        (lambda p: p.id_token_overrides.update(nonce="a-different-logins-nonce"), NonceMismatchError, "nonce mismatch"),
        (lambda p: setattr(p, "id_token_signer", Signer()), SignatureInvalidError, "signature verification failed"),
        (
            lambda p: p.id_token_overrides.update(at_hash="AAAAAAAAAAAAAAAAAAAAAA"),
            TokenValidationError,
            "access token hash",
        ),
    ],
)
def test_a_bad_id_token_is_rejected_with_its_own_reason_and_creates_no_session(world, setup, error, reason):
    service, provider, sessions, *_ = world
    setup(provider)
    attempt, state, code = begin(service, provider)
    with pytest.raises(error, match=reason):
        service.complete(attempt_id=attempt, state=state, code=code)
    assert sessions.count() == 0


def test_an_id_token_signed_with_an_unaccepted_algorithm_is_rejected(world):
    service, provider, sessions, *_ = world
    provider.id_token_factory = lambda nonce, _access: jwt.encode(
        id_token_claims(provider.clock, nonce=nonce), key="", algorithm="none", headers={"kid": provider.signer.kid}
    )
    attempt, state, code = begin(service, provider)
    with pytest.raises(UnsupportedAlgorithmError):
        service.complete(attempt_id=attempt, state=state, code=code)
    assert sessions.count() == 0


def test_a_token_response_without_an_id_token_is_refused(world):
    service, provider, *_ = world
    provider.omit_id_token = True
    attempt, state, code = begin(service, provider)
    with pytest.raises(ProviderError, match="no ID token"):
        service.complete(attempt_id=attempt, state=state, code=code)


def signed_in(world, extra=()):
    service, provider, _sessions, _clock, _ = world
    attempt, state, code = begin(service, provider, extra)
    issued = service.complete(attempt_id=attempt, state=state, code=code)
    return issued, service.resolve(issued.raw_session_id)


def test_resolve_returns_the_session_until_it_is_idle_too_long(world):
    service, _, _, clock, _ = world
    issued, _ = signed_in(world)
    clock.advance(minutes=14)
    assert service.resolve(issued.raw_session_id) is not None
    clock.advance(minutes=14)  # 14 minutes after the last use: still inside 15
    assert service.resolve(issued.raw_session_id) is not None
    clock.advance(minutes=16)
    assert service.resolve(issued.raw_session_id) is None


def test_a_session_ends_at_its_absolute_lifetime_even_with_constant_use(world):
    service, _, _, clock, _ = world
    issued, _ = signed_in(world)
    for _ in range(34):
        clock.advance(minutes=14)
        service.resolve(issued.raw_session_id)
    clock.advance(minutes=14)
    assert service.resolve(issued.raw_session_id) is None


def test_unknown_and_empty_cookie_values_resolve_to_nothing(world):
    service, *_ = world
    assert service.resolve(None) is None
    assert service.resolve("") is None
    assert service.resolve("nope") is None


def test_refresh_rotates_the_refresh_token_and_the_old_one_stops_working(world):
    service, provider, sessions, *_ = world
    _, session = signed_in(world)
    old = session.tokens.refresh_token
    renewed = service.refresh(session)
    assert renewed.tokens.refresh_token != old
    assert sessions.get(session.session_id_hash).tokens.refresh_token == renewed.tokens.refresh_token
    with pytest.raises(ProviderError) as reused:
        provider.refresh(old)
    assert reused.value.code == "invalid_grant"
    assert renewed.tokens.id_token == session.tokens.id_token  # a refresh response carries none; the login's is kept


def test_a_refused_refresh_drops_the_session(world):
    service, provider, sessions, *_ = world
    _, session = signed_in(world)
    provider.refresh_tokens[session.tokens.refresh_token] = False
    with pytest.raises(ProviderError):
        service.refresh(session)
    assert sessions.count() == 0


def test_refreshing_an_ended_session_is_refused(world):
    service, _, sessions, *_ = world
    _, session = signed_in(world)
    sessions.delete(session.session_id_hash)
    with pytest.raises(SessionNotFoundError):
        service.refresh(session)


def test_the_access_token_is_refreshed_only_when_it_is_about_to_expire(world):
    service, provider, _, clock, _ = world
    issued, session = signed_in(world)
    token, same = service.access_token(session)
    assert token == session.tokens.access_token
    assert same.tokens == session.tokens
    clock.advance(seconds=100)  # 20 s left of 120, inside the 30 s margin
    live = service.resolve(issued.raw_session_id)
    assert live is not None
    token_after, renewed = service.access_token(live)
    assert token_after != token
    assert renewed.tokens.refresh_token != session.tokens.refresh_token
    assert [name for name, _ in provider.requests].count("refresh") == 1


def test_sign_out_removes_the_session_and_revokes_the_refresh_token(world):
    service, provider, sessions, *_ = world
    issued, session = signed_in(world)
    assert service.sign_out(issued.raw_session_id) is True
    assert sessions.count() == 0
    assert provider.refresh_tokens[session.tokens.refresh_token] is False
    assert service.resolve(issued.raw_session_id) is None


def test_sign_out_ends_the_local_session_even_when_revocation_fails(world):
    service, provider, sessions, *_ = world
    issued, _ = signed_in(world)

    def broken(token):
        raise ProviderError("server_error")

    provider.revoke = broken
    assert service.sign_out(issued.raw_session_id) is False
    assert sessions.count() == 0


def test_sign_out_without_a_session_is_harmless(world):
    service, *_ = world
    assert service.sign_out(None) is False
    assert service.sign_out("never-issued") is False


def test_csrf_comparison(world):
    service, *_ = world
    _, session = signed_in(world)
    assert service.csrf_valid(session, session.csrf_token)
    assert not service.csrf_valid(session, "wrong")
    assert not service.csrf_valid(session, None)


def test_the_session_id_is_stored_only_as_a_hash(world):
    _, _, sessions, *_ = world
    issued, session = signed_in(world)
    assert session.session_id_hash == hash_session_id(issued.raw_session_id) != issued.raw_session_id
    assert sessions.get(issued.raw_session_id) is None


def test_old_sessions_are_purged_when_a_new_one_starts(world):
    _service, _provider, sessions, clock, _ = world
    signed_in(world)
    clock.advance(hours=1)
    signed_in(world)
    assert sessions.count() == 1


def test_a_granted_extra_scope_is_recorded_on_the_session(world):
    _, provider, *_ = world
    provider.granted_scope = "openid reports:read"
    _, session = signed_in(world, extra=["reports:read"])
    assert "reports:read" in session.scopes
    assert timedelta(seconds=120) == session.tokens.access_expires_at - session.created_at
