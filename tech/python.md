# Python 3.12

## What it is

Python is a programming language. You write instructions in text files that end in `.py`, and a program called the **interpreter** reads them and does what they say. This repository targets Python 3.12 (`requires-python = ">=3.12"` in `pyproject.toml`, and the Docker image is `python:3.12-slim-bookworm`). Your own laptop may run a newer one: the `Makefile` picks `python3.13` first, then `python3.12`, then `python3`.

A **module** is one `.py` file. A **package** is a folder of modules with an `__init__.py` file in it. A **library** is a package somebody else wrote that you install and `import`.

## Why this repository uses it

The lesson is about doing OAuth login correctly. The interesting part is the *rules* (which checks, in which order, with which error), and Python keeps the rules short enough to read. The standard library supplies the building blocks of a safe login: `secrets` for unguessable values, `hashlib` and `base64` for PKCE, `hmac` for safe comparisons, `urllib.parse` for URLs, `threading` for locks, `logging` and `json` for structured logs.

## Where it appears

| Path | What it does with Python |
| --- | --- |
| `src/oidc_login/domain/` | Pure rules: PKCE, ID-token claim checks, scopes, value objects, named errors. Standard library only. |
| `src/oidc_login/application/` | `LoginService` (the whole flow) and the `Protocol` ports it needs. |
| `src/oidc_login/infrastructure/` | Adapters: the HTTP provider client, the JWT verifier, in-memory stores, settings, logging, clock. |
| `src/oidc_login/interfaces/` | The Flask app, gunicorn config, health program, demo scenario, scripted browser. |
| `tests/` | pytest tests: unit (no provider), integration and e2e (against Keycloak). |

## How it works underneath

1. You run `python something.py` or a command like `gunicorn`. The operating system starts one **process**: the interpreter.
2. The interpreter **compiles** your text into **bytecode** and runs it. The Dockerfile sets `PYTHONDONTWRITEBYTECODE=1` so the container does not write `__pycache__` folders.
3. When code says `import x`, the interpreter finds `x` once, runs it, and keeps it in memory. Later imports reuse it.
4. Every value is an **object** in memory. Names point at objects; an object with no names left is freed.
5. **Type hints** like `user_id: int` are labels for humans and tools. Python does not enforce them when running; `mypy` (`tech/mypy.md`) checks them beforehand.
6. A **thread** is a path of execution inside one process. Several threads share memory, which is why this app guards its stores with locks.

## Walkthrough of this repository's use

### `from __future__ import annotations`

Almost every file starts with it. Type hints are stored as text instead of being evaluated at import time, so a hint can name a class defined later in the file.

### Dataclasses: value objects, and keeping secrets out of printouts

```python
@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    id_token: str = field(repr=False)
    access_expires_at: datetime = field(compare=False)
    scope: str = ""
```
`@dataclass` writes `__init__`, `__repr__` and `__eq__` from the field list. `frozen=True` makes instances read-only; `slots=True` stores fields compactly and rejects misspelled attributes. `field(repr=False)` hides a field from `repr()`, which is what `print`, logs and tracebacks show: printing a `TokenSet` shows only the expiry and scope, never a token (`TokenSet(access_expires_at=..., scope='')`). `field(compare=False)` leaves a field out of `==`. Frozen means "changing" an object builds a new one: `dataclasses.replace(session, last_seen_at=now)` copies with one field changed (`resolve()` and `refresh()` do this).

`PendingLogin.code_verifier` is also `repr=False`; `UserSession` hides its tokens and CSRF token the same way.

### Properties

```python
@property
def scopes(self) -> frozenset[str]:
    return frozenset(self.tokens.scope.split())
```
`@property` makes a method read like a field: `session.scopes`. `.split()` cuts a string at spaces; `frozenset` is an immutable set, so membership tests (`"reports:read" in session.scopes`) are fast and nobody can add to it.

### Exceptions as a vocabulary

```python
class TokenValidationError(LoginError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

class AudienceMismatchError(TokenValidationError):
    def __init__(self) -> None:
        super().__init__("audience claim does not match client id")
```
A hierarchy: `LoginError` is the base of everything the flow raises on purpose; `TokenValidationError` has one subclass per failed check. A caller can catch the family (`except TokenValidationError`) or one member, and `error.reason` says what failed. In `app.py` the route logs the reason and shows the user only a generic page.

### Protocols and keyword-only arguments

```python
class IdentityProvider(Protocol):
    def exchange_code(self, *, code: str, code_verifier: str) -> TokenResponse: ...
```
A `Protocol` is a description of required methods; any class with those methods fits (`OidcProvider` does). The bare `*` forces keyword arguments, so `exchange_code(code=..., code_verifier=...)` cannot be called with the two strings in the wrong order.

### Unions, optionals and narrowing

`str | None` means "text or nothing". Code must handle `None` before using the value. In `_audiences` (`domain/claims.py`), `isinstance(value, str)` and `isinstance(value, list)` branch on the real type of data from JSON; anything else raises `MissingClaimError("aud")`.

### Time and durations

`datetime.now(UTC)` is a timezone-aware current time; `timedelta(seconds=30)` is a length of time. `expected.now >= expires_at + expected.leeway` means "the token expired, allowing 30 seconds of clock difference". `datetime.fromtimestamp(value, UTC)` converts the token's `exp` (seconds since 1970) into a datetime.

### Standard-library security building blocks

- `secrets.token_urlsafe(nbytes)` (`infrastructure/clock.py`): random text from the OS's secure random generator. 32 bytes give 43 characters; 64 give the 86-character PKCE verifier.
- `hashlib.sha256(...).hexdigest()`: the session id is stored only as this fingerprint (`hash_session_id`).
- `hmac.compare_digest(a, b)`: compares in time that does not depend on where the first difference is. Used for `state`, `nonce`, CSRF tokens and `at_hash`.
- `base64.urlsafe_b64encode` plus `.rstrip(b"=")`: the PKCE challenge and `at_hash` encoding.
- `urllib.parse.urlencode`, `urlsplit`, `parse_qs`: building and reading URLs; `Settings._validate` uses `urlsplit` to reject a redirect URI with a query or fragment, or with `http` on a non-localhost host.
- `threading.Lock()` and `with self._lock:`: only one thread at a time inside the block. The in-memory stores and the refresh path use it.
- `re.compile(r"[A-Za-z0-9\-._~]{43,128}")` and `.fullmatch`: allow-list validation.
- `logging` and `json.dumps(..., separators=(",", ":"))` with a redacting formatter: `tech/json.md`.
- `html.parser.HTMLParser` (`interfaces/scripted_browser.py`): finds the login form in the provider's page for the scripted browser.

### Context managers

`with self._lock:` and `with httpx.Client(...)`-style blocks run set-up, your code, then clean-up even when an exception happens.

### Command-line programs

`pyproject.toml` declares `oidc-login-health` and `oidc-login-demo` (`tech/pyproject-and-setuptools.md`). `health_cli.main()` returns `0` or `1`, and `sys.exit(main())` turns that into the process **exit code**; Docker's health check and `make health` read it. `demo_cli.main()` runs the scenario and prints `PASS`/`FAIL` per step.

## Try it yourself

1. See which interpreter the project uses:
   ```bash
   .venv/bin/python --version
   ```
   Expect `Python 3.12.x` or newer (the maintainer's machine printed `Python 3.13.12`).
2. Run the claim checks with no provider:
   ```bash
   .venv/bin/python - <<'EOF'
   from datetime import datetime, UTC, timedelta
   from oidc_login.domain.claims import Expectations, check_id_token_claims
   from oidc_login.domain.errors import TokenValidationError
   now = datetime.now(UTC)
   claims = {"iss": "https://idp.test", "aud": "app", "exp": int((now + timedelta(minutes=5)).timestamp()),
             "nonce": "n1", "sub": "u1", "preferred_username": "demo-user"}
   exp = Expectations("https://idp.test", "app", "n1", now)
   print(check_id_token_claims(claims, exp))
   try: check_id_token_claims({**claims, "aud": "other"}, exp)
   except TokenValidationError as e: print(type(e).__name__, "-", e.reason)
   EOF
   ```
   Expect `Identity(subject='u1', username='demo-user', email=None)` and `AudienceMismatchError - audience claim does not match client id`.
3. See a secret stay out of a printout:
   ```bash
   .venv/bin/python -c "
   from datetime import datetime, UTC
   from oidc_login.domain.models import TokenSet
   print(TokenSet('secret-access', 'secret-refresh', 'secret-id', datetime.now(UTC)))"
   ```
   Expect `TokenSet(access_expires_at=datetime.datetime(...), scope='')` with none of the three secret strings.
4. Make a token like the app's:
   ```bash
   .venv/bin/python -c "import secrets; t = secrets.token_urlsafe(64); print(len(t))"
   ```
   Expect `86`.

## Mistakes people make

- Using `random` for tokens: it is predictable. Use `secrets`.
- Comparing secrets with `==`.
- Printing or logging objects that contain tokens. `field(repr=False)` and the redacting log formatter both guard against it.
- Mutable default arguments (`def f(x=[])`).
- Naive datetimes (no timezone).
- Shared mutable state across threads without a lock.
- `assert` for validating input: Python can run with assertions off (`-O`). The code raises named exceptions instead.

## Check yourself

1. What does `field(repr=False)` do, and why use it on tokens?
   *It hides the field from `repr`, so printing the object or logging it never shows the token.*
2. Why does `exchange_code` take keyword-only arguments?
   *To prevent swapping the code and the verifier by position.*
3. What is a `Protocol`?
   *A description of required methods; `mypy` checks that adapters match.*
4. Why `hmac.compare_digest` and not `==`?
   *It does not leak, through timing, how much of a secret matched.*
5. What does `with self._lock:` guarantee?
   *Only one thread runs that block at a time.*

## Further reading

- Python 3.12 documentation: https://docs.python.org/3.12/
- `dataclasses`: https://docs.python.org/3.12/library/dataclasses.html
- `secrets`: https://docs.python.org/3.12/library/secrets.html
- `hmac.compare_digest`: https://docs.python.org/3.12/library/hmac.html#hmac.compare_digest
- `threading.Lock`: https://docs.python.org/3.12/library/threading.html#lock-objects
