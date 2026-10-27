"""WSGI entry point: ``gunicorn "oidc_login.interfaces.wsgi:build_app()"``."""

from __future__ import annotations

import logging
import os

from flask import Flask

from oidc_login.infrastructure.logging import configure_logging
from oidc_login.infrastructure.settings import Settings
from oidc_login.interfaces.composition import Container, build_container
from oidc_login.interfaces.http.app import create_app

_containers: list[Container] = []


def build_app() -> Flask:
    """Read settings from the environment and return the application.

    Raises ``ConfigError`` (and so refuses to start) on a missing or invalid setting. The provider is contacted
    lazily, on the first sign-in or readiness probe, so the app starts even while the provider is still booting.
    """
    settings = Settings.from_environment(os.environ)
    configure_logging(settings.log_level)
    container = build_container(settings)
    _containers.append(container)
    logging.getLogger("oidc_login").info(
        "started", extra={"app_env": settings.app_env, "issuer": settings.issuer, "client_id": settings.client_id}
    )
    return create_app(container)


def close_all() -> None:
    """Close the HTTP clients of every application this process built (graceful shutdown)."""
    while _containers:
        _containers.pop().provider.close()
    logging.getLogger("oidc_login").info("provider client closed")
