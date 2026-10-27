"""Fixtures for the tests that talk to the identity provider (make up). The unit tests need none of this."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from oidc_login.interfaces.demo_cli import Scenario

os.environ.setdefault("APP_ENV", "test")


@pytest.fixture
def scenario() -> Iterator[Scenario]:
    """A fresh app (no sessions, no cached state) wired to the real provider, and scripted browsers."""
    env = dict(os.environ)
    env.setdefault("DEMO_USER_PASSWORD", "local-only-demo-user-password")
    instance = Scenario(env)
    yield instance
    instance.close()
