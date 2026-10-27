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
