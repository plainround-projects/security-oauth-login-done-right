import io
import json
import logging
from datetime import timedelta

from oidc_login.domain.models import PendingLogin
from oidc_login.infrastructure.logging import REDACTED, JsonFormatter, configure_logging, redact
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
from tests.fakes import START, FakeClock


def test_tokens_codes_secrets_and_cookies_are_redacted_by_field_name():
    fields = {
        "access_token": "a",
        "refresh_token": "r",
        "id_token": "i",
        "code": "c",
        "code_verifier": "v",
        "client_secret": "s",
        "nonce": "n",
        "state": "st",
        "session_id": "x",
        "cookie": "c",
        "authorization": "Bearer x",
        "subject": "user-1",
        "event": "login.completed",
        "status": 200,
    }
    cleaned = redact(fields)
    assert {key for key, value in cleaned.items() if value == REDACTED} == set(fields) - {"subject", "event", "status"}


def test_the_formatter_writes_one_redacted_json_line():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.oidc.json")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("exchanged", extra={"subject": "user-1", "access_token": "eyJhbGciOi-secret"})
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")
    first, second = (json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{"))
    assert first["subject"] == "user-1"
    assert first["access_token"] == REDACTED
    assert "eyJhbGciOi-secret" not in stream.getvalue()
    assert "ValueError: boom" in second["exception"]
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING


def pending(attempt_id, created_at=START):
    return PendingLogin(attempt_id, "state", "nonce", "v" * 64, "openid", created_at)


def test_a_pending_login_can_be_taken_once():
    store = InMemoryPendingLoginStore(FakeClock(), 600)
    store.put(pending("a"))
    assert store.pop("a") is not None
    assert store.pop("a") is None
    assert store.pop("never") is None


def test_expired_attempts_are_dropped_when_a_new_one_arrives_and_the_store_is_bounded():
    clock = FakeClock()
    store = InMemoryPendingLoginStore(clock, 600, max_entries=3)
    store.put(pending("old", clock.now()))
    clock.advance(seconds=601)
    for name in ("a", "b", "c", "d"):
        store.put(pending(name, clock.now()))
    assert store.pop("old") is None
    assert store.pop("a") is None  # the oldest was evicted to keep the store at three
    assert store.pop("d") is not None


def test_the_session_store_replaces_only_sessions_that_still_exist_and_purges_the_inactive():
    from dataclasses import replace

    from oidc_login.domain.models import Identity, TokenSet, UserSession

    tokens = TokenSet("a", "r", "i", START + timedelta(minutes=2), "openid")
    session = UserSession("h1", Identity("u", "u"), tokens, "csrf", START, START, START + timedelta(hours=8))
    store = InMemorySessionStore()
    store.add(session)
    store.replace(replace(session, csrf_token="new"))
    replaced = store.get("h1")
    assert replaced is not None
    assert replaced.csrf_token == "new"
    store.delete("h1")
    store.replace(session)  # a refresh that finishes after sign-out must not resurrect the session
    assert store.get("h1") is None
    assert store.count() == 0
    store.add(session)
    store.add(replace(session, session_id_hash="h2", last_seen_at=START + timedelta(minutes=30)))
    assert store.purge_inactive(START + timedelta(minutes=31), timedelta(minutes=15)) == 1
    assert store.count() == 1
