"""In-memory stores for pending logins and sessions.

The tokens in a session never touch a disk or a database, which is a feature here. The price is that the state belongs
to one process: run one worker with several threads, and a restart signs everyone out. The ports are five short
methods each; a Redis adapter is the way to scale out (see ARCHITECTURE.md).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from oidc_login.application.ports import Clock
from oidc_login.domain.models import PendingLogin, UserSession

MAX_PENDING = 10_000


class InMemoryPendingLoginStore:
    """Single-use, time-limited login attempts, bounded in number so a flood of ``/login`` cannot fill memory."""

    def __init__(self, clock: Clock, ttl_seconds: int, max_entries: int = MAX_PENDING) -> None:
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max = max_entries
        self._items: dict[str, PendingLogin] = {}
        self._lock = threading.Lock()

    def put(self, pending: PendingLogin) -> None:
        """Remember an attempt; expired ones are dropped first, then the oldest if the store is still full."""
        with self._lock:
            now = self._clock.now()
            for key in [k for k, item in self._items.items() if item.created_at + self._ttl <= now]:
                del self._items[key]
            while len(self._items) >= self._max:
                del self._items[next(iter(self._items))]
            self._items[pending.attempt_id] = pending

    def pop(self, attempt_id: str) -> PendingLogin | None:
        """Remove and return the attempt (single use)."""
        with self._lock:
            return self._items.pop(attempt_id, None)


class InMemorySessionStore:
    """Sessions by the hash of their cookie value."""

    def __init__(self) -> None:
        self._items: dict[str, UserSession] = {}
        self._lock = threading.Lock()

    def add(self, session: UserSession) -> None:
        """Store a session."""
        with self._lock:
            self._items[session.session_id_hash] = session

    def get(self, session_id_hash: str) -> UserSession | None:
        """Fetch a session."""
        with self._lock:
            return self._items.get(session_id_hash)

    def replace(self, session: UserSession) -> None:
        """Overwrite a session that still exists; a session deleted in the meantime stays deleted."""
        with self._lock:
            if session.session_id_hash in self._items:
                self._items[session.session_id_hash] = session

    def delete(self, session_id_hash: str) -> UserSession | None:
        """Remove and return a session."""
        with self._lock:
            return self._items.pop(session_id_hash, None)

    def purge_inactive(self, now: datetime, idle: timedelta) -> int:
        """Drop sessions past their lifetime or idle longer than ``idle``."""
        with self._lock:
            stale = [k for k, s in self._items.items() if now >= s.expires_at or now >= s.last_seen_at + idle]
            for key in stale:
                del self._items[key]
            return len(stale)

    def count(self) -> int:
        """How many sessions are held."""
        with self._lock:
            return len(self._items)
