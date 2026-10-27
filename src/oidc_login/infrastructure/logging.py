"""Structured (JSON) logging with redaction, so a token that reaches a log call never reaches the log."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

REDACTED = "[redacted]"
_SENSITIVE_KEY = re.compile(
    r"pass(word|wd)?|secret|token|cookie|authorization|csrf|session|api[_-]?key|code|verifier|nonce|state",
    re.IGNORECASE,
)
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace the value of every field whose name looks sensitive (tokens, codes, secrets, cookies)."""
    return {key: REDACTED if _SENSITIVE_KEY.search(key) else value for key, value in fields.items()}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, and the call's extra fields, redacted."""

    def format(self, record: logging.LogRecord) -> str:
        """Render a record as a single JSON line."""
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(redact({key: value for key, value in record.__dict__.items() if key not in _RESERVED}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str) -> None:
    """Send every log record to standard error as JSON at the given level."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
