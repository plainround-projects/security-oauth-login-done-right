# `.env` files and environment variables

## What it is

An **environment variable** is a named text value that the operating system hands to every program it starts (`PATH`, `HOME`). Programs read them to find out how they should behave. A **`.env` file** is a plain text file of `NAME=value` lines used by tools to set many variables at once. It is a convention, not a standard, and different tools read it slightly differently.

## Why this repository uses it

Rule one of the lesson: **no secret in code**. The client secret, the demo user's password and the provider's admin password come from the environment, the app refuses to start when a required one is missing, and the real values live in a git-ignored `.env`. The twelve-factor app method calls this "config in the environment". The same `.env` feeds three consumers: the app, Docker Compose, and (through Compose) Keycloak's realm import.

## Where it appears

| Path | What it does |
| --- | --- |
| `.env.example` | The tracked template with safe local-only placeholder values. |
| `.env` | Your local copy, created by `make env`; git-ignored and excluded from Docker builds. |
| `Makefile` | `-include .env` and `export`: make reads the file and passes the values to every recipe (`idp-check` uses `OIDC_ISSUER`). |
| `docker-compose.yml` | Substitutes `${VAR}` placeholders from `.env`, passes some into Keycloak (they fill `${...}` placeholders in the realm file), and loads the whole file into the app container with `env_file`. |
| `src/oidc_login/infrastructure/settings.py` | `Settings.from_environment(os.environ)` reads, validates and types everything. |
| `tests/conftest.py` | Sets `APP_ENV=test` if unset and gives the demo user's password a local-only default. |

(The `.env*` files are deliberately not displayed in this note: the editor environment denies reading them, and they hold credentials. Variable names below come from the code.)

## How it works underneath

1. When a program starts, the parent process passes a copy of its environment (a dictionary of strings) to the child. Changes made by the child do not flow back.
2. `make` with `-include .env` parses the `NAME=value` lines as Make variables; `export` puts them into the environment of recipes.
3. Docker Compose reads `.env` from the project folder for `${...}` substitution, and `env_file:` injects every line into a container's environment.
4. In Python, `os.environ` is that dictionary. Every value is a string; the code converts and validates (`int(...)`, allowed sets).

### Ideas you need first

- **A process and its environment.** Every running program (process) receives, when it starts, a private copy of a list of `NAME=value` pairs called its environment. Programs read them to learn how they should behave.
- **A string.** All environment values are text, even `8047`; a program that wants a number must convert it, and a bad value must be rejected at start-up.
- **A default.** A value used when the variable is not set. `${NAME:-default}` in Compose and `env.get("NAME", default)` in Python both mean that.
- **A secret.** A value that must stay private (a password, a key). Plain settings may be shared; secrets must not be committed.
- **A template file.** `.env.example` has every name and safe local values and is committed; `.env` is your own copy and is not.

## Walkthrough of this repository's use

The variables the application understands (from `settings.py`):

| Variable | Meaning | Default |
| --- | --- | --- |
| `APP_ENV` | `development`, `test` or `production` | `production` |
| `APP_HOST`, `APP_PORT` | Where to listen | `127.0.0.1`, `3000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `OIDC_ISSUER` | **Required.** The provider's issuer URL, compared exactly with the token's `iss` | none |
| `OIDC_DISCOVERY_BASE` | Where to fetch the discovery document and keys if different (the app container uses `http://keycloak:8080/realms/demo`) | the issuer |
| `OIDC_CLIENT_ID` | **Required.** The registered client (`notes-app`) | none |
| `OIDC_CLIENT_SECRET` | **Required.** The client's secret | none |
| `OIDC_REDIRECT_URI` | **Required.** The one registered callback URL | none |
| `OIDC_ALLOWED_EXTRA_SCOPES` | Comma-separated scopes a request may add | `reports:read` |
| `COOKIE_SECURE` | Whether cookies carry `Secure`; `false` refused in production | `true` |
| `OIDC_HTTP_TIMEOUT_SECONDS` | Timeout for calls to the provider | `10` |
| `SESSION_IDLE_SECONDS`, `SESSION_ABSOLUTE_SECONDS` | Session lifetimes | `900`, `28800` |
| `LOGIN_ATTEMPT_TTL_SECONDS` | How long a started login can be completed | `600` |
| `ACCESS_TOKEN_REFRESH_MARGIN_SECONDS` | Refresh when the access token has less than this left | `30` |
| `TRUSTED_PROXY_COUNT` | Reverse proxies whose forwarded headers to believe | `0` |

Compose also uses `KEYCLOAK_PORT`, `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD` and `DEMO_USER_PASSWORD` for the Keycloak container (and the demo's scripted user).

Key behaviors in code:

```python
def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise ConfigError(f"{name} is required (set it in .env or the environment)")
    return value
```
No default secret exists anywhere: a missing issuer, client id, client secret or redirect URI stops start-up with a clear message. The client secret is a `field(repr=False)` of the settings dataclass, so printing the settings does not show it.

```python
def _read_int(env, name, default, *, minimum=1) -> int:
    ...
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
```
A typo in a number is an error at start-up, not a crash in the middle of a request.

`Settings._validate` also refuses, in production, a redirect URI that is not `https`, an issuer that is not `https`, and `COOKIE_SECURE=false`; it refuses an `http` redirect URI for any host but localhost; a redirect URI with a query or fragment; and an idle session limit longer than the absolute one. So a copied-over development configuration cannot weaken production.

Where the format differs between tools: the `Makefile` and Compose both accept simple `NAME=value` lines; avoid quotes, spaces around `=`, and `$` in values, which they treat differently.

### Line by line: `src/oidc_login/infrastructure/settings.py`

```python
"""Configuration from the environment (twelve-factor), validated once at start-up."""
```

The docstring: configuration from the environment (the twelve-factor method), validated once at start-up.

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit
```

Imports: `Mapping`, `dataclass` and `field`, `Literal` and `urlsplit` (splits an address into scheme, host, path and so on).

```python
AppEnv = Literal["development", "test", "production"]
_ENVIRONMENTS: tuple[AppEnv, ...] = ("development", "test", "production")
_TRUE = {"1", "true", "yes", "on"}
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
```

`AppEnv` allows exactly three texts. `_ENVIRONMENTS` lists them, `_TRUE` is the set of texts that mean "on", and `_LOOPBACK` is the set of host names that mean "this same machine" (`localhost`, `127.0.0.1`, `::1`).

```python
class ConfigError(Exception):
    """A setting is missing or invalid. Raised before the app serves anything."""
```

`ConfigError` is raised before the app serves anything.

```python
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
```

`_read_int` returns the default for a missing or empty variable, raises `ConfigError` for text that is not a whole number or is below the minimum (`minimum` is keyword-only because of the `*`).

```python
def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise ConfigError(f"{name} is required (set it in .env or the environment)")
    return value
```

`_require` returns a variable's value or raises `ConfigError` naming it. There is no default for required settings, in particular none for the client secret.

```python
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
```

`Settings` holds everything the app reads: the environment name, host, port, log level, the issuer, the discovery base address, the client id and secret (`field(repr=False)` keeps the secret out of the printed form), the redirect address, the extra-scope allow-list, whether cookies are Secure, the HTTP timeout, the session times, the pending-login time, the refresh margin and the number of trusted proxies.

```python
    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Settings:
        """Build and validate settings; raise ``ConfigError`` naming the first problem."""
        app_env = env.get("APP_ENV", "production")
        if app_env not in _ENVIRONMENTS:
            raise ConfigError(f"APP_ENV must be one of {', '.join(_ENVIRONMENTS)}, got {app_env!r}")
```

`from_environment` checks `APP_ENV` first (default `production`, the safe default).

```python
        issuer = _require(env, "OIDC_ISSUER").rstrip("/")
```

The issuer is required and a trailing `/` is removed, because the issuer must be compared as an exact text.

```python
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
```

Each setting is read with its default: host `127.0.0.1`, port 3000, log level `INFO`, discovery base equal to the issuer unless `OIDC_DISCOVERY_BASE` is set, required client id, secret and redirect address, extra scopes from a comma-separated list defaulting to `reports:read` (`filter(None, ...)` drops empty pieces), `COOKIE_SECURE` default true, HTTP timeout 10, idle 900, absolute 28,800, login-attempt lifetime 600, refresh margin 30 and trusted proxies 0.

```python
        settings._validate()
        return settings
```

Cross-checks run, then the settings are returned.

```python
    def _validate(self) -> None:
        redirect = urlsplit(self.redirect_uri)
        if redirect.scheme not in {"http", "https"} or not redirect.netloc or redirect.fragment or redirect.query:
            raise ConfigError("OIDC_REDIRECT_URI must be an absolute http(s) URL without query or fragment")
```

`_validate` splits the redirect address. It must have an `http` or `https` scheme and a host, and no query or fragment; the provider requires an exact match, and query or fragment parts would invite open-redirect tricks.

```python
        if self.app_env == "production" and redirect.scheme != "https":
            raise ConfigError("OIDC_REDIRECT_URI must use https in production")
```

In production the redirect address must be `https`.

```python
        if redirect.scheme == "http" and redirect.hostname not in _LOOPBACK:
            raise ConfigError("an http OIDC_REDIRECT_URI is only accepted for localhost")
```

An `http` redirect address is accepted only for localhost.

```python
        if self.app_env == "production" and not self.cookie_secure:
            raise ConfigError("COOKIE_SECURE=false is not accepted in production")
```

In production `COOKIE_SECURE=false` is refused.

```python
        if urlsplit(self.issuer).scheme not in {"http", "https"}:
            raise ConfigError("OIDC_ISSUER must be an absolute http(s) URL")
        if self.app_env == "production" and urlsplit(self.issuer).scheme != "https":
            raise ConfigError("OIDC_ISSUER must use https in production")
```

The issuer must be an absolute `http` or `https` address, and `https` in production.

```python
        if self.session_idle_seconds > self.session_absolute_seconds:
            raise ConfigError("SESSION_IDLE_SECONDS must not exceed SESSION_ABSOLUTE_SECONDS")
```

The idle time may not exceed the absolute lifetime.

## Try it yourself

1. Create the file and see it is ignored:
   ```bash
   make env && git status --short | grep -c "\.env$"
   ```
   Expect `created .env from .env.example` (or nothing if it exists) and `0`: git does not see `.env`.
2. Prove the app refuses to start without its client secret:
   ```bash
   .venv/bin/python -c "
   from oidc_login.infrastructure.settings import Settings
   Settings.from_environment({'OIDC_ISSUER': 'http://localhost:8180/realms/demo', 'OIDC_CLIENT_ID': 'notes-app',
                              'OIDC_REDIRECT_URI': 'http://localhost:3000/callback'})"
   ```
   Expect `ConfigError: OIDC_CLIENT_SECRET is required (set it in .env or the environment)`.
3. Prove production refuses plain HTTP:
   ```bash
   .venv/bin/python -c "
   from oidc_login.infrastructure.settings import Settings
   Settings.from_environment({'APP_ENV': 'production', 'OIDC_ISSUER': 'https://idp.example.test/realms/demo',
                              'OIDC_CLIENT_ID': 'c', 'OIDC_CLIENT_SECRET': 's', 'OIDC_REDIRECT_URI': 'http://localhost:3000/callback'})"
   ```
   Expect `ConfigError: OIDC_REDIRECT_URI must use https in production`.
4. Run the settings tests: `.venv/bin/pytest tests/unit/test_settings.py -q`. Expect all pass.

## Mistakes people make

- Committing `.env`. It is ignored and excluded from images.
- Giving production a default secret "for convenience".
- Treating all variables as strings and finding out at 3 a.m. that `"false"` is truthy. Here parsing is explicit.
- Printing the environment or settings in logs. `Settings.client_secret` is `repr=False`, and the log formatter redacts sensitive names.
- Assuming a child can change a parent's variables.

## Check yourself

1. What type is every environment variable's value?
   *A string.*
2. Why does `Settings.from_environment` take a mapping argument?
   *So tests can pass their own dictionary instead of changing the real environment.*
3. What does `-include .env` followed by `export` do in the Makefile?
   *Reads the file into Make variables and passes them to every recipe's environment.*
4. What happens when `OIDC_CLIENT_SECRET` is missing?
   *`ConfigError` at start-up, before anything is served.*
5. Why is `.env.example` safe to commit?
   *It contains only local-only placeholders, never real credentials.*

## Further reading

- The Twelve-Factor App, config: https://12factor.net/config
- Docker Compose environment variables: https://docs.docker.com/compose/how-tos/environment-variables/
- Python `os.environ`: https://docs.python.org/3.12/library/os.html#os.environ
