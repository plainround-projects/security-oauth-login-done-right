"""Configuration from the environment (twelve-factor), validated once at start-up."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

AppEnv = Literal["development", "test", "production"]
_ENVIRONMENTS: tuple[AppEnv, ...] = ("development", "test", "production")
_TRUE = {"1", "true", "yes", "on"}
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class ConfigError(Exception):
    """A setting is missing or invalid. Raised before the app serves anything."""


def _read_int(env: Mapping[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise ConfigError(f"{name} is required (set it in .env or the environment)")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the application reads from its environment."""

    app_env: AppEnv
    host: str
    port: int
    log_level: str
    issuer: str
    discovery_base: str
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    allowed_extra_scopes: frozenset[str]
    cookie_secure: bool
    http_timeout_seconds: int
    session_idle_seconds: int
    session_absolute_seconds: int
    pending_ttl_seconds: int
    refresh_margin_seconds: int
    trusted_proxy_count: int

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Settings:
        """Build and validate settings; raise ``ConfigError`` naming the first problem."""
        app_env = env.get("APP_ENV", "production")
        if app_env not in _ENVIRONMENTS:
            raise ConfigError(f"APP_ENV must be one of {', '.join(_ENVIRONMENTS)}, got {app_env!r}")
        issuer = _require(env, "OIDC_ISSUER").rstrip("/")
        settings = cls(
            app_env=app_env,
            host=env.get("APP_HOST", "127.0.0.1"),
            port=_read_int(env, "APP_PORT", 3000),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            issuer=issuer,
            discovery_base=env.get("OIDC_DISCOVERY_BASE", issuer).rstrip("/"),
            client_id=_require(env, "OIDC_CLIENT_ID"),
            client_secret=_require(env, "OIDC_CLIENT_SECRET"),
            redirect_uri=_require(env, "OIDC_REDIRECT_URI"),
            allowed_extra_scopes=frozenset(
                filter(None, env.get("OIDC_ALLOWED_EXTRA_SCOPES", "reports:read").split(","))
            ),
            cookie_secure=env.get("COOKIE_SECURE", "true").lower() in _TRUE,
            http_timeout_seconds=_read_int(env, "OIDC_HTTP_TIMEOUT_SECONDS", 10),
            session_idle_seconds=_read_int(env, "SESSION_IDLE_SECONDS", 900),
            session_absolute_seconds=_read_int(env, "SESSION_ABSOLUTE_SECONDS", 28800),
            pending_ttl_seconds=_read_int(env, "LOGIN_ATTEMPT_TTL_SECONDS", 600),
            refresh_margin_seconds=_read_int(env, "ACCESS_TOKEN_REFRESH_MARGIN_SECONDS", 30),
            trusted_proxy_count=_read_int(env, "TRUSTED_PROXY_COUNT", 0, minimum=0),
        )
        settings._validate()
        return settings

    def _validate(self) -> None:
        redirect = urlsplit(self.redirect_uri)
        if redirect.scheme not in {"http", "https"} or not redirect.netloc or redirect.fragment or redirect.query:
            raise ConfigError("OIDC_REDIRECT_URI must be an absolute http(s) URL without query or fragment")
        if self.app_env == "production" and redirect.scheme != "https":
            raise ConfigError("OIDC_REDIRECT_URI must use https in production")
        if redirect.scheme == "http" and redirect.hostname not in _LOOPBACK:
            raise ConfigError("an http OIDC_REDIRECT_URI is only accepted for localhost")
        if self.app_env == "production" and not self.cookie_secure:
            raise ConfigError("COOKIE_SECURE=false is not accepted in production")
        if urlsplit(self.issuer).scheme not in {"http", "https"}:
            raise ConfigError("OIDC_ISSUER must be an absolute http(s) URL")
        if self.app_env == "production" and urlsplit(self.issuer).scheme != "https":
            raise ConfigError("OIDC_ISSUER must use https in production")
        if self.session_idle_seconds > self.session_absolute_seconds:
            raise ConfigError("SESSION_IDLE_SECONDS must not exceed SESSION_ABSOLUTE_SECONDS")
