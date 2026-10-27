"""gunicorn settings.

Start with ``gunicorn -c python:oidc_login.interfaces.gunicorn_conf "oidc_login.interfaces.wsgi:build_app()"``.

One worker with several threads: sessions and pending logins live in this process's memory (see ARCHITECTURE.md).
SIGTERM makes the master stop accepting connections and lets in-flight requests finish (up to ``graceful_timeout``)
before the worker closes its HTTP client in ``worker_exit``.
"""

from __future__ import annotations

import os
from typing import Any

bind = f"{os.environ.get('APP_HOST', '127.0.0.1')}:{os.environ.get('APP_PORT', '3000')}"
workers = 1
threads = 8
worker_class = "gthread"
timeout = 30
graceful_timeout = 20
keepalive = 5
control_socket_disable = True
limit_request_line = 4094
limit_request_fields = 50
accesslog = None  # the application writes one structured line per request
errorlog = "-"
logconfig_dict: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "oidc_login.infrastructure.logging.JsonFormatter"}},
    "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stderr"}},
    "root": {"level": "INFO", "handlers": ["stderr"]},
    "loggers": {"gunicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False}},
}


def worker_exit(server: object, worker: object) -> None:
    """Called in the worker as it exits: close the provider's HTTP client."""
    from oidc_login.interfaces.wsgi import close_all

    close_all()
