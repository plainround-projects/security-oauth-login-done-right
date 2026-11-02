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

### Ideas you need first

If you have never programmed, read this list once. Each idea is used in the walkthrough below.

- **A program and a file.** A program is a list of instructions. Python programs live in plain text files whose names end in `.py`. You can open them in any text editor.
- **A directory (folder) and a path.** A directory holds files and other directories. A **path** is the address of a file, such as `src/oidc_login/domain/pkce.py`: start in `src`, go into `oidc_login`, then `domain`, then the file `pkce.py`.
- **A variable.** A name that points at a value: `limit = 5` makes the name `limit` point at the number 5. Later code can say `limit` and get 5.
- **A value and its type.** Every value has a kind: whole numbers (`int`), text (`str`), true or false (`bool`), "nothing" (`None`), and containers. A **list** is an ordered row of values (`[1, 2, 3]`). A **tuple** is a list that cannot be changed (`(1, 2)`). A **set** is a bag of distinct values with no order (`{1, 2}`); a **frozenset** is a set that cannot be changed. A **dict** (dictionary) maps keys to values (`{"name": "alice"}`).
- **A function.** A named, reusable piece of code: `def add(a, b): return a + b`. You **call** it with `add(1, 2)`. The values you pass are **arguments**; the names inside the function are **parameters**. `return` hands a result back.
- **A class and an object.** A class is a blueprint; an **object** (an instance) is one thing built from it. A class bundles data (**attributes**) and functions (**methods**). Inside a method, the first parameter, `self`, is the object itself. `__init__` is the method Python runs when an object is created. A class can **inherit** from another (`class A(B)`): it gets B's methods and may add more. `super()` means "the parent class".
- **A module, a package and `import`.** A module is one `.py` file; a package is a directory of modules with an `__init__.py` file. `import x` or `from x import y` makes code from another module available. The first time a module is imported, Python runs it once and remembers it.
- **An exception.** A signal that something went wrong. `raise SomeError("message")` stops the normal flow. `try: ... except SomeError: ...` catches it and runs other code instead. `finally:` runs in every case. An exception that nothing catches ends the program with a **traceback** (a list of the calls that led to the error).
- **A decorator.** A line starting with `@` above a function or class, such as `@dataclass`. It wraps or registers the thing below it. `@app.get("/healthz")` registers the function below as the handler for that web address.
- **A type hint.** Labels such as `def f(user_id: int) -> str`. They say what kinds of values go in and out. Python itself ignores them when the program runs; a checker called mypy reads them (`tech/mypy.md`).
- **An f-string.** Text with values inserted: `f"user {name}"` becomes `user alice` when `name` is `"alice"`.
- **A comprehension.** A compact way to build a list, set or dict from another: `[x * 2 for x in numbers]` is "for each x in numbers, take x times 2".
- **A generator and `yield`.** A function that hands back values one at a time with `yield`, pausing between them.
- **A context manager and `with`.** `with something as name:` runs set-up code, then your indented block, then clean-up code, even if the block raises. Files, locks and database connections use it.
- **A process.** A running copy of a program. The operating system gives each process its own memory. Starting `python script.py` makes one process.
- **A thread.** A path of execution inside one process. Several threads share that process's memory and can run at the same time.
- **Standard output, standard error, exit code.** `print(...)` writes to standard output (stdout), the normal output stream. A second stream, standard error (stderr), is for problems and logs. When a process ends it returns a number, the **exit code**: 0 means success, anything else means failure.
- **An environment variable.** A named piece of text that the operating system gives to every process it starts, such as `PATH` or `HOME`. Programs read them with `os.environ`. The values are always text.
- **Standard library.** The large set of modules that ship with Python itself (`json`, `hashlib`, `secrets`, `re`, `logging`...). They need no installation. Anything else is a **third-party library**, installed with a package manager (`tech/uv-and-lock-files.md`).

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

### Every module, one by one

The package is `src/oidc_login/`, in four layers, each allowed to use only the ones below it (`tech/import-linter.md`): `interfaces` (talks to the outside world) uses `infrastructure` (the HTTP client to the provider, the token verifier, the in-memory stores, settings, logging), which uses `application` (the sign-in flow), which uses `domain` (the rules). Each folder's `__init__.py` holds only a one-line description in a **docstring** (a text string placed first in a module, class or function to document it); its presence is what makes the folder a package. Every module starts with `from __future__ import annotations`, which makes type hints plain text so a hint may name something defined later.

#### Layer 1: `domain/`, the rules

**`domain/pkce.py`** (`tech/pkce.md`). `_VERIFIER = re.compile(r"[A-Za-z0-9\-._~]{43,128}")` is a **regular expression** (a pattern language for text) meaning "43 to 128 characters, each a letter, digit, hyphen, dot, underscore or tilde". `is_valid_verifier` uses `fullmatch`, which requires the whole string to fit. `challenge_for(verifier)` raises `ValueError` for an invalid verifier, then computes `base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")`: encode the text to bytes, take its SHA-256 fingerprint (32 bytes), write the bytes with URL-safe base64 letters, drop the `=` padding, turn the bytes back into text.

**`domain/scopes.py`.** `BASE_SCOPE = "openid profile email"`. `requested_scope(extra, allowed)` builds `sorted({scope for scope in extra if scope in allowed})`: a **set comprehension** that keeps only allow-listed extras (a set drops duplicates), sorted, then `" ".join([BASE_SCOPE, *wanted])` (the `*` spreads the list). `require(granted, needed)` raises `InsufficientScopeError(needed)` when the scope is missing.

**`domain/errors.py`.** `LoginError` is the base of everything raised on purpose. `TokenValidationError(reason)` keeps `reason`; its subclasses each fix one message: `SignatureInvalidError`, `UnsupportedAlgorithmError(algorithm)`, `IssuerMismatchError`, `AudienceMismatchError`, `AuthorizedPartyMismatchError`, `TokenExpiredError`, `TokenNotYetValidError`, `NonceMismatchError`, `MissingClaimError(claim)`. Others: `StateMismatchError`, `ProviderError(code, description)` (the provider's own `error` value, such as `invalid_grant`), `ProviderUnavailableError`, `SessionNotFoundError`, `InsufficientScopeError(scope)`. Each class is a name that the web layer maps to exactly one response.

**`domain/models.py`.** Frozen dataclasses (`@dataclass(frozen=True, slots=True)`: written once, never changed, compact). `PendingLogin` is what the app remembers between sending the browser away and its return: attempt id, `state`, `nonce`, the PKCE `code_verifier` (declared `field(repr=False)` so printing the object never shows it), scope, creation time. `TokenSet` holds the three tokens (all `repr=False`), the access token's expiry (`field(compare=False)`: ignored when comparing two objects) and the granted scope. `Identity` is subject, username, email. `UserSession` holds the identity, the `TokenSet`, a CSRF token and three times; its `scopes` **property** (a method used like a field) returns `frozenset(self.tokens.scope.split())`. `ProviderMetadata` has the six discovery fields; `TokenResponse` is a token endpoint reply before validation (`id_token: str | None` because a refresh reply may omit it).

**`domain/claims.py`** (`tech/oauth2-and-openid-connect.md`). `Expectations` holds what this login expects: issuer, client id, nonce, the current time and a leeway of 30 seconds (`timedelta(seconds=30)`). `_timestamp(claims, name)` reads a numeric claim as a UTC datetime and rejects booleans and non-numbers (`isinstance(value, bool) or not isinstance(value, int | float)`). `_audiences` accepts a text or a list of texts. `check_id_token_claims` runs the checks in order, each raising its own error: issuer must equal exactly; the client id must be among the audiences; with several audiences `azp` must equal the client id; `exp` must exist and `now >= exp + leeway` means expired; `iat` more than the leeway in the future is "not valid yet"; the `nonce` must be text equal (compared with `hmac.compare_digest`, which compares in time that does not reveal where two strings first differ) to this attempt's; `sub` must be non-empty. It returns an `Identity` (username falls back to the subject). `check_access_token_hash` verifies `at_hash` when the claim is present: the left half of the SHA-256 of the access token, base64url-encoded.

#### Layer 2: `application/`

**`application/ports.py`.** Six `Protocol`s (a description of required methods that any class can satisfy without inheriting): `IdentityProvider` (`metadata`, `authorization_url`, `exchange_code`, `refresh`, `revoke`, `userinfo`), `TokenVerifier` (`verify`), `PendingLoginStore` (`put`, `pop`), `SessionStore` (`add`, `get`, `replace`, `delete`, `count`, `purge_inactive`), `Clock` (`now`), `TokenGenerator` (`token`).

**`application/login_flow.py`** is the heart: `LoginService`.
- `LoginConfig` (frozen dataclass): issuer, client id, allowed extra scopes, and numbers: pending TTL 600 s, idle 900 s, absolute 28,800 s, refresh margin 30 s, leeway 30 s.
- `hash_session_id(raw)`: SHA-256 hex of the cookie value.
- `__init__` receives seven collaborators (**dependency injection**: it is handed what it needs, so tests hand it fakes) and creates a `threading.Lock()` so two threads cannot refresh the same session at once.
- `start(extra_scopes)`: makes the verifier (64 random bytes), attempt id, state and nonce with the token generator; builds a `PendingLogin`; stores it; asks the provider for the authorization URL with `challenge_for(verifier)`; logs `login started`; returns the URL, the attempt id and its lifetime.
- `complete(attempt_id=, state=, code=)`: `_claim_attempt` (below); refuses a missing code; exchanges the code (server-to-server) with the stored verifier; requires an ID token; verifies its signature (`TokenVerifier`); runs `check_id_token_claims` with this attempt's nonce; runs `check_access_token_hash`; creates a random session id and a `UserSession`; purges inactive sessions; stores it; logs `login completed`; returns the raw session id for the cookie.
- `resolve(raw)`: hash, fetch, delete and return `None` if past the absolute expiry or idle too long, else store `replace(session, last_seen_at=now)` (`dataclasses.replace` copies a frozen object with one field changed).
- `refresh(session)`: inside `with self._refresh_lock:`, re-read the session; refuse if gone or without a refresh token; call the provider; on a provider failure delete the session and re-raise; otherwise store the new tokens (`_token_set` keeps the old refresh token if the reply has none).
- `access_token(session)`: refresh first if the token expires within the margin.
- `sign_out(raw)`: delete the session, then ask the provider to revoke the refresh token; returns whether the provider confirmed; the local session is gone either way.
- `csrf_valid` (static method, `hmac.compare_digest`), `_claim_attempt` (no cookie or state: refuse; `pop` the attempt so it is single-use; compare `state`; refuse if older than the TTL), and `_token_set`.

#### Layer 3: `infrastructure/`

**`clock.py`**: `SystemClock.now()` is `datetime.now(UTC)`; `SecretsTokenGenerator.token(nbytes=32)` is `secrets.token_urlsafe(nbytes)`.

**`oidc_provider.py`** (`tech/httpx.md`): `OidcProvider` implements `IdentityProvider`. `__init__` builds the discovery URL and one `httpx.Client` with a 10-second timeout, 3 seconds to connect and no redirect following. `metadata()` fetches once under a lock, validates that `issuer` equals the configured one and that six fields exist, and caches it. `jwks()` fetches the key set. `authorization_url` builds the query with `urlencode`. `exchange_code`, `refresh` and `revoke` POST forms with the client id and secret in the body (`_post`) and are never retried; `_token_request` turns the reply into a `TokenResponse`, mapping bad shapes to `ProviderError("invalid_response", ...)`. `userinfo` GETs with `Authorization: Bearer <token>`. `_get_json` retries idempotent GETs at 0.2, 0.5 and 1.0 seconds on network errors and 5xx. `_error_from` reads `error` and `error_description` from an error body (or falls back to `http_<status>`), logs the code and returns a `ProviderError`.

**`jwks_verifier.py`** (`tech/jwt-and-jwks.md`, `tech/pyjwt.md`): `JwksTokenVerifier.verify` reads the unverified header, refuses any algorithm but `RS256`, picks the key by `kid` (refetching the key set at most once every 30 seconds for an unknown `kid`), and decodes with signature checking only; `_load` builds a dictionary `kid -> PyJWK` keeping only signing keys with the right algorithm and logging, not failing on, a malformed one.

**`memory_stores.py`**: `InMemoryPendingLoginStore` (a dictionary under a lock; `put` first drops expired attempts and, if the store holds 10,000, the oldest; `pop` removes and returns, single-use). `InMemorySessionStore` (a dictionary keyed by session-id hash under a lock; `replace` only overwrites a session that still exists, so a sign-out in between stays a sign-out; `purge_inactive` drops expired and idle ones; `count`).

**`settings.py`**: `Settings.from_environment` reads, converts and validates every variable once (`tech/dotenv.md` lists them) and `_validate` refuses an invalid redirect URI (not http/https, has a query or fragment), an `http` redirect URI outside localhost, `https` missing in production, `COOKIE_SECURE=false` in production, a non-http(s) issuer, and an idle limit above the absolute one. `client_secret` is `field(repr=False)`.

**`logging.py`**: same design as the sibling project, with a longer redaction pattern: `pass|passwd|password|secret|token|cookie|authorization|csrf|session|api_key|code|verifier|nonce|state`.

#### Layer 4: `interfaces/`

**`composition.py`**: `Container` and `build_container(settings)` create the clock, the provider, the verifier (given `provider.jwks` as its key source), the two stores and the `LoginService`. **`wsgi.py`**: `build_app()` reads settings, configures logging, builds the container (no provider call yet: the app starts even while the provider is still booting), logs `started`, returns the Flask app; `close_all()` closes each provider HTTP client and logs `provider client closed`. **`gunicorn_conf.py`**: settings plus `worker_exit` (`tech/gunicorn.md`). **`health_cli.py`**: `main()` GETs `http://127.0.0.1:<port>/healthz` with `urllib.request.urlopen(..., timeout=3)` and returns 0 for status 200, else 1 (liveness only). **`http/security.py`**: cookie names, header table, `set_cookie`, `clear_cookie`, `apply_security_headers`. **`http/app.py`**: the Flask app (`tech/flask.md`).

**`scripted_browser.py`**: stand-ins for people. `_LoginForm` is a small `html.parser.HTMLParser` subclass that finds the login `<form>` in Keycloak's page (by `id="kc-form-login"` or an action containing `login-actions/authenticate`) and collects its hidden inputs. `ProviderBrowser` (the user at the provider) keeps cookies by hand in a dictionary: Keycloak marks some cookies `Secure` even on `http://localhost`, which a real browser accepts but a plain HTTP client's cookie jar rejects; `_send` adds the `Cookie` header and records each `Set-Cookie` (a `Max-Age=0` or empty value deletes it); `authorize(url)` GETs the authorization URL, and if it gets a login page fills in username and password and POSTs, returning the final answer as a `Hop(status, location, body)`. `AppBrowser` (the user at the app) wraps Flask's test client on `https://localhost`, with `follow_callback(location)` (GET the callback path and query) and `sign_in(provider)` (the whole round trip).

**`demo_cli.py`** (`oidc-login-demo`): `Scenario` builds the real container and Flask app in-process, with one method per claim, each returning a `Step(name, passed, detail)` and never raising on a failed expectation: `discovery`, `start_login`, `authenticate`, `complete_login`, `id_token_validation` (forges five bad tokens: a wrong audience and expiry by changing the expectations, a token signed with a freshly generated RSA key, one with `alg: none`, a wrong nonce), `mismatched_state`, `login_csrf`, `replayed_callback`, `lookalike_redirect_uri` (three near-miss addresses), `code_reuse`, `wrong_pkce_verifier`, `session_facts`, `refresh_rotation`, `logout`, `scope_check`, `public_client_needs_pkce`. `run_scenario` calls them in order (16 steps) inside `try/finally` so the HTTP clients are always closed; `main` prints `PASS`/`FAIL` per step and `N of 16 checks passed`, returning 1 on any failure. Helpers: `_query(url)` returns the query string as a dictionary; `_cookie_attributes` extracts a cookie's value and attributes from `Set-Cookie` headers; `_replace_query_value` rewrites one query parameter.

### Line by line: `src/oidc_login/__init__.py`

A file named `__init__.py` marks a folder as a Python **package**, a folder of modules that can be imported by name.

```python
"""Sign-in with an OpenID Connect provider: code flow with PKCE, validated ID tokens, server-side sessions."""

__version__ = "0.1.0"
```

A docstring (a text in triple quotes at the top of a file that documents it) saying what the package does, and `__version__`, the version text by convention.

### Line by line: `src/oidc_login/application/__init__.py`

```python
"""The sign-in use cases and the ports they need. Depends on the domain only."""
```

The marker of the `application` layer: the sign-in use cases and the ports (interfaces) they need. It depends on the domain only; import-linter fails the build if that changes.

### Line by line: `src/oidc_login/domain/__init__.py`

```python
"""Rules and value objects of the sign-in flow. Depends on nothing outside the standard library."""
```

The marker of the `domain` layer: rules and plain data, using only Python's standard library.

### Line by line: `src/oidc_login/infrastructure/__init__.py`

```python
"""Adapters: the provider's HTTP API, JWT verification, in-memory stores, settings, logging. Depends on the application
and domain layers."""
```

The marker of the `infrastructure` layer: the adapters for the provider's HTTP API, JWT verification, the in-memory stores, settings and logging.

### Line by line: `src/oidc_login/interfaces/__init__.py`

```python
"""Entry points: the HTTP application, the WSGI and gunicorn wiring, and the command-line programs. Nothing depends
on this layer."""
```

The marker of the `interfaces` layer: the HTTP application, the WSGI and gunicorn wiring and the command-line programs. Nothing depends on it.

### Line by line: `src/oidc_login/interfaces/http/__init__.py`

```python
"""The Flask application: routes, templates, cookies, CSRF check and security headers."""
```

The marker of the `http` package: routes, templates, cookies, the CSRF check and the security headers.

### Line by line: `src/oidc_login/domain/errors.py`

```python
"""Named errors. Messages are the reasons the lesson asks for: each failure says what was actually wrong."""
```

The docstring: named errors whose messages are the reasons the lesson asks for. Each failure says what was actually wrong.

```python
from __future__ import annotations
```

`from __future__ import annotations` keeps type hints as text instead of evaluating them at load time.

```python
class LoginError(Exception):
    """Base class of every error the sign-in flow raises on purpose."""
```

`LoginError` is the base class of every error raised on purpose.

```python
class TokenValidationError(LoginError):
    """An ID token failed a check. ``reason`` names the check; the other subclasses carry a fixed one."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
```

`TokenValidationError` is for an ID token that failed a check. It keeps the `reason` text; the subclasses below each carry a fixed reason.

```python
class SignatureInvalidError(TokenValidationError):
    """The signature does not verify against the provider's key."""

    def __init__(self, detail: str = "signature verification failed") -> None:
        super().__init__(detail)
```

`SignatureInvalidError`: the signature does not verify against the provider's key. It has a default detail.

```python
class UnsupportedAlgorithmError(TokenValidationError):
    """The token names a signing algorithm the app does not accept (``none``, ``HS256`` and the like)."""

    def __init__(self, algorithm: str) -> None:
        super().__init__(f"signing algorithm {algorithm!r} is not accepted")
        self.algorithm = algorithm
```

`UnsupportedAlgorithmError`: the token names a signing algorithm the app does not accept, such as `none` (no signature at all) or `HS256` (a shared-secret algorithm that an attacker could abuse with the public key). `{algorithm!r}` puts the name in quotes in the message.

```python
class IssuerMismatchError(TokenValidationError):
    """``iss`` is not the provider this app signs in with."""

    def __init__(self) -> None:
        super().__init__("issuer claim does not match the provider")
```

`IssuerMismatchError`: the `iss` claim (who issued the token) is not the provider the app signs in with.

```python
class AudienceMismatchError(TokenValidationError):
    """``aud`` does not include this app's client id."""

    def __init__(self) -> None:
        super().__init__("audience claim does not match client id")
```

`AudienceMismatchError`: the `aud` claim (who the token is for) does not include this app's client id.

```python
class AuthorizedPartyMismatchError(TokenValidationError):
    """``azp`` names another client."""

    def __init__(self) -> None:
        super().__init__("authorized party claim does not match client id")
```

`AuthorizedPartyMismatchError`: the `azp` claim (the client the token was issued to) names another client.

```python
class TokenExpiredError(TokenValidationError):
    """``exp`` has passed."""

    def __init__(self) -> None:
        super().__init__("token has expired")
```

`TokenExpiredError`: the `exp` time has passed.

```python
class TokenNotYetValidError(TokenValidationError):
    """``iat`` or ``nbf`` is in the future beyond the allowed clock skew."""

    def __init__(self) -> None:
        super().__init__("token is not valid yet")
```

`TokenNotYetValidError`: `iat` (issued at) is in the future beyond the allowed clock difference.

```python
class NonceMismatchError(TokenValidationError):
    """``nonce`` is not the value this login attempt sent: possible token substitution."""

    def __init__(self) -> None:
        super().__init__("nonce mismatch: possible token substitution")
```

`NonceMismatchError`: the `nonce` is not the one this login attempt sent. The message says "possible token substitution": someone may have given the app a token meant for another login.

```python
class MissingClaimError(TokenValidationError):
    """A required claim is absent."""

    def __init__(self, claim: str) -> None:
        super().__init__(f"required claim {claim!r} is missing")
        self.claim = claim
```

`MissingClaimError`: a required claim is absent; it keeps the claim name.

```python
class StateMismatchError(LoginError):
    """The callback does not belong to a login this browser started (wrong, reused or missing ``state``, or no
    login-attempt cookie)."""
```

`StateMismatchError`: the callback does not belong to a login this browser started (wrong, reused or missing `state`, or no login-attempt cookie).

```python
class ProviderError(LoginError):
    """The provider answered with an OAuth error. ``code`` is its ``error`` value, for example ``invalid_grant``."""

    def __init__(self, code: str, description: str = "") -> None:
        super().__init__(f"{code}: {description}" if description else code)
        self.code = code
        self.description = description
```

`ProviderError`: the provider answered with an OAuth error. `code` is its `error` value, for example `invalid_grant`, and the message joins the code and the description when there is one.

```python
class ProviderUnavailableError(LoginError):
    """The provider could not be reached or answered with something unusable."""
```

`ProviderUnavailableError`: the provider could not be reached or answered with something unusable.

```python
class SessionNotFoundError(LoginError):
    """No live session for the cookie value (unknown, expired or signed out)."""
```

`SessionNotFoundError`: no live session for the cookie value (unknown, expired or signed out).

```python
class InsufficientScopeError(LoginError):
    """The session was not granted a scope the route needs."""

    def __init__(self, scope: str) -> None:
        super().__init__(f"scope {scope!r} was not granted")
        self.scope = scope
```

`InsufficientScopeError`: the session was not granted a scope that a route needs.

### Line by line: `src/oidc_login/domain/models.py`

```python
"""Immutable value objects of the sign-in flow."""
```

The docstring: immutable value objects, records that cannot change after creation.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
```

Imports: `dataclass` (writes the repetitive methods of a data-holding class), `field` (per-field options) and `datetime`.

```python
@dataclass(frozen=True, slots=True)
class PendingLogin:
    """What the app remembers between sending the browser to the provider and the browser coming back.

    The verifier never leaves the server. The ``attempt_id`` is also stored in a short-lived cookie, which ties the
    callback to the browser that started the login.
    """

    attempt_id: str
    state: str
    nonce: str
    code_verifier: str = field(repr=False)
    scope: str
    created_at: datetime
```

`PendingLogin` is what the app remembers between sending the browser to the provider and the browser coming back: an attempt id, the `state`, the `nonce`, the PKCE `code_verifier`, the scope and the creation time. `frozen=True` makes it read-only and `slots=True` keeps it compact. `field(repr=False)` keeps the verifier out of the printed form, so it cannot leak into a log. The docstring says the verifier never leaves the server and the attempt id also goes in a short-lived cookie, tying the callback to the browser that started the login.

```python
@dataclass(frozen=True, slots=True)
class TokenSet:
    """Tokens as the provider issued them. They live on the server only."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    id_token: str = field(repr=False)
    access_expires_at: datetime = field(compare=False)
    scope: str = ""
```

`TokenSet` holds the tokens as the provider issued them: the access token, the optional refresh token, the ID token and when the access token expires. They live on the server only. All three secrets are hidden from the printed form. `compare=False` on the expiry means two token sets are equal even if only the expiry differs.

```python
@dataclass(frozen=True, slots=True)
class Identity:
    """Who the ID token says signed in."""

    subject: str
    username: str
    email: str | None = None
```

`Identity` is who the ID token says signed in: the subject (a stable id the provider gives the user), a username and an optional email.

```python
@dataclass(frozen=True, slots=True)
class UserSession:
    """A signed-in session: the identity, the tokens (server side), the CSRF token and the lifetimes."""

    session_id_hash: str
    identity: Identity
    tokens: TokenSet = field(repr=False)
    csrf_token: str = field(repr=False)
    created_at: datetime = field(compare=False)
    last_seen_at: datetime = field(compare=False)
    expires_at: datetime = field(compare=False)

    @property
    def scopes(self) -> frozenset[str]:
        """The scopes the provider granted for this sign-in."""
        return frozenset(self.tokens.scope.split())
```

`UserSession` is a signed-in session: the hash of the cookie value, the identity, the tokens and CSRF token (hidden from printing) and three times that do not take part in equality. The `scopes` property splits the granted scope text on spaces into a frozen set.

```python
@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """The parts of the provider's discovery document the app uses."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str
    revocation_endpoint: str
```

`ProviderMetadata` holds the parts of the provider's discovery document the app uses: the issuer and five endpoint addresses.

```python
@dataclass(frozen=True, slots=True)
class TokenResponse:
    """A token endpoint response, before it is validated. A refresh response may omit the ID token."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    id_token: str | None = field(repr=False)
    expires_in: int
    scope: str
```

`TokenResponse` is a token endpoint answer before validation. The ID token may be `None` because a refresh answer may omit it.

### Line by line: `src/oidc_login/domain/pkce.py`

**PKCE** (Proof Key for Code Exchange, pronounced "pixy") stops a stolen authorization code from being useful. The app invents a random secret (the verifier), sends only its hash (the challenge) when it starts the login, and sends the verifier itself only when it trades the code for tokens. The provider checks that the hash of the verifier matches the challenge it saw earlier. An attacker who steals the code on its way back does not know the verifier.

```python
"""PKCE (RFC 7636): the challenge derived from a verifier, so a stolen authorization code is useless on its own."""
```

The docstring names RFC 7636, the standard that defines PKCE.

```python
from __future__ import annotations

import base64
import hashlib
import re
```

Imports: `base64`, `hashlib` (SHA-256) and `re`.

```python
_VERIFIER = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
```

`_VERIFIER` is a regular expression: 43 to 128 characters, each a letter, digit, hyphen, dot, underscore or tilde (the RFC's "unreserved" characters).

```python
def is_valid_verifier(verifier: str) -> bool:
    """True for a verifier of 43 to 128 unreserved characters, as the RFC requires."""
    return _VERIFIER.fullmatch(verifier) is not None
```

`is_valid_verifier` is true when the whole text matches (`fullmatch`).

```python
def challenge_for(verifier: str) -> str:
    """``base64url(sha256(verifier))`` without padding: the S256 method, the only one this app uses."""
    if not is_valid_verifier(verifier):
        raise ValueError("code verifier must be 43 to 128 unreserved characters")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
```

`challenge_for` refuses an invalid verifier, then computes SHA-256 of the verifier's ASCII bytes, encodes the 32 bytes as **base64url** (base64 with `-` and `_` in place of `+` and `/`, safe in a URL) and strips the trailing `=` padding. This is the `S256` method, the only one the app uses (the other method, `plain`, would send the verifier itself).

### Line by line: `src/oidc_login/domain/scopes.py`

A **scope** is a permission name that the app asks the provider for, such as `email` or `offline_access`. The user (or the provider's policy) grants some or all of them.

```python
"""OAuth scopes: parsing a request and checking that a grant covers what a route needs."""
```

The docstring: parsing a request and checking that a grant covers what a route needs.

```python
from __future__ import annotations

from collections.abc import Iterable

from oidc_login.domain.errors import InsufficientScopeError
```

Imports: `Iterable` and the scope error.

```python
BASE_SCOPE = "openid profile email"
```

`BASE_SCOPE` is the text `openid profile email`: `openid` asks for an ID token, `profile` and `email` for the claims the app shows.

```python
def requested_scope(extra: Iterable[str], allowed: frozenset[str]) -> str:
    """The base scopes (``openid`` for the ID token, ``profile`` and ``email`` for the claims the app shows) plus the
    extra scopes the caller asked for, each of which must be on the allow-list.

    Anything else is dropped rather than forwarded: a request parameter must not be able to widen what the app asks
    the provider for.
    """
    wanted = sorted({scope for scope in extra if scope in allowed})
    return " ".join([BASE_SCOPE, *wanted])
```

`requested_scope` takes extra scope names from the caller and an allow-list. It keeps only names on the allow-list (a set comprehension), sorts them and joins them to the base scopes with spaces. The docstring explains: anything else is dropped rather than passed on, so a request parameter cannot widen what the app asks the provider for.

```python
def require(granted: frozenset[str], needed: str) -> None:
    """Raise ``InsufficientScopeError`` unless the grant includes ``needed``."""
    if needed not in granted:
        raise InsufficientScopeError(needed)
```

`require` raises `InsufficientScopeError` unless the granted set includes the needed scope.

### Line by line: `src/oidc_login/domain/claims.py`

An **ID token** is a signed statement from the provider, in JWT form (`tech/jwt-and-jwks.md`), that says who signed in. Its **claims** are the fields of the statement. The signature proves the provider wrote it; this file checks that the statement is about this login and this app.

```python
"""The checks on an ID token's claims (OpenID Connect Core, section 3.1.3.7), run after the signature is verified.

Each check raises its own named error, so a rejected token says which check failed. The signature itself is checked
first, by the ``TokenVerifier`` port: every claim below is meaningless on a token that could have been forged.
"""
```

The docstring: the checks on an ID token's claims (OpenID Connect Core, section 3.1.3.7), run after the signature is verified. Each check raises its own named error. The signature is checked first because every claim is meaningless on a token that could have been forged.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import base64
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
```

Imports: `base64`, `hashlib`, `hmac` (for a timing-safe comparison), `Mapping`, `dataclass`, date and time types and `Any`.

```python
from oidc_login.domain.errors import (
    AudienceMismatchError,
    AuthorizedPartyMismatchError,
    IssuerMismatchError,
    MissingClaimError,
    NonceMismatchError,
    TokenExpiredError,
    TokenNotYetValidError,
    TokenValidationError,
)
```

The eight error classes the checks can raise.

```python
from oidc_login.domain.models import Identity
```

The `Identity` record.

```python
@dataclass(frozen=True, slots=True)
class Expectations:
    """What this particular login attempt expects to find in the token."""

    issuer: str
    client_id: str
    nonce: str
    now: datetime
    leeway: timedelta = timedelta(seconds=30)
```

`Expectations` is what this login attempt expects: the issuer, the client id, the nonce, the current time and a **leeway** of 30 seconds, the clock difference the checks tolerate between the provider's clock and the app's.

```python
def _timestamp(claims: Mapping[str, Any], name: str) -> datetime | None:
    value = claims.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MissingClaimError(name)
    return datetime.fromtimestamp(value, UTC)
```

`_timestamp` reads a numeric date claim. A missing claim gives `None`; a boolean or a non-number raises `MissingClaimError` (a `True` would otherwise count as the number 1); a valid one becomes a UTC `datetime`. `int | float` in `isinstance` tests for either type.

```python
def _audiences(claims: Mapping[str, Any]) -> list[str]:
    value = claims.get("aud")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise MissingClaimError("aud")
```

`_audiences` reads `aud`, which may be one text or a list of texts. Anything else raises `MissingClaimError`.

```python
def check_id_token_claims(claims: Mapping[str, Any], expected: Expectations) -> Identity:
    """Return the identity in the token, or raise the error of the first check that fails.

    Order: issuer, audience (and authorized party when there are several audiences), expiry, issued-at, nonce,
    subject. All comparisons are exact; none is a prefix or pattern match.
    """
```

`check_id_token_claims` returns the identity or raises the error of the first failing check, in this order: issuer, audience (and authorized party when there are several), expiry, issued-at, nonce, subject. All comparisons are exact.

```python
    if claims.get("iss") != expected.issuer:
        raise IssuerMismatchError
```

The `iss` claim must equal the expected issuer exactly.

```python
    audiences = _audiences(claims)
    if expected.client_id not in audiences:
        raise AudienceMismatchError
```

The client id must be among the audiences.

```python
    if len(audiences) > 1 and claims.get("azp") != expected.client_id:
        raise AuthorizedPartyMismatchError
```

With several audiences, `azp` must equal the client id (OpenID Connect Core says so).

```python
    expires_at = _timestamp(claims, "exp")
    if expires_at is None:
        raise MissingClaimError("exp")
    if expected.now >= expires_at + expected.leeway:
        raise TokenExpiredError
```

`exp` is required; the token is expired when now is at or past `exp` plus the leeway.

```python
    issued_at = _timestamp(claims, "iat")
    if issued_at is not None and issued_at - expected.leeway > expected.now:
        raise TokenNotYetValidError
```

If `iat` is present and lies more than the leeway in the future, the token is not yet valid.

```python
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not hmac.compare_digest(nonce.encode(), expected.nonce.encode()):
        raise NonceMismatchError
```

The nonce must be text and equal to the expected one. `hmac.compare_digest` compares in constant time, so the response time does not reveal how many characters matched.

```python
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise MissingClaimError("sub")
```

`sub` must be a non-empty text.

```python
    username = claims.get("preferred_username")
    email = claims.get("email")
    return Identity(
        subject=subject,
        username=username if isinstance(username, str) and username else subject,
        email=email if isinstance(email, str) else None,
    )
```

The username is `preferred_username` if it is non-empty text, else the subject; the email is kept only if it is text. The `Identity` is returned.

```python
def check_access_token_hash(claims: Mapping[str, Any], access_token: str) -> None:
    """If the ID token carries ``at_hash``, the access token delivered with it must match (OpenID Connect Core,
    section 3.1.3.8): the left half of the SHA-256 of the access token, base64url encoded. Absent is allowed."""
    expected = claims.get("at_hash")
    if expected is None:
        return
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    actual = base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode("ascii")
    if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), actual.encode()):
        raise TokenValidationError("access token hash does not match the ID token")
```

`check_access_token_hash` implements OpenID Connect Core 3.1.3.8. If the ID token has an `at_hash` claim, it must equal the left half of the SHA-256 of the access token, base64url encoded without padding; this ties the access token to the ID token. An absent `at_hash` is allowed. A mismatch raises `TokenValidationError`.

### Line by line: `src/oidc_login/application/ports.py`

A **port** is an interface: names and types of methods a use case needs, with no code. A real adapter in `infrastructure` does the work; tests use fakes.

```python
"""Ports: what the sign-in flow needs from the outside world. Adapters live in ``infrastructure``."""
```

The docstring: what the sign-in flow needs from the outside world.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
from datetime import datetime, timedelta
from typing import Any, Protocol
```

`datetime`, `timedelta`, `Any` and `Protocol` (a way to describe an interface by shape: any class with these methods fits).

```python
from oidc_login.domain.models import PendingLogin, ProviderMetadata, TokenResponse, UserSession
```

The domain records used in the signatures.

```python
class IdentityProvider(Protocol):
    """The OpenID Connect provider, as the back channel and the redirect see it."""

    def metadata(self) -> ProviderMetadata:
        """The provider's discovery document, validated (its issuer is the configured one)."""

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str, scope: str) -> str:
        """Where to send the browser: code flow, S256 challenge, the one registered redirect URI."""

    def exchange_code(self, *, code: str, code_verifier: str) -> TokenResponse:
        """Trade the code and the PKCE verifier for tokens, server to server. Raises ``ProviderError``."""

    def refresh(self, refresh_token: str) -> TokenResponse:
        """Trade a refresh token for new tokens; the provider rotates the refresh token. Raises ``ProviderError``."""

    def revoke(self, refresh_token: str) -> None:
        """Ask the provider to invalidate a refresh token (RFC 7009)."""

    def userinfo(self, access_token: str) -> dict[str, Any]:
        """Call the provider's userinfo endpoint with an access token."""
```

`IdentityProvider` is the OpenID Connect provider as the back channel and the redirect see it. `metadata` returns the discovery document (a JSON document the provider publishes that lists its addresses), validated so its issuer is the configured one. `authorization_url` builds the address to send the browser to: code flow, S256 challenge and the one registered redirect address. `exchange_code` trades the code plus the PKCE verifier for tokens, server to server. `refresh` trades a refresh token for new tokens; the provider rotates the refresh token. `revoke` asks the provider to invalidate a refresh token (RFC 7009). `userinfo` calls the provider's userinfo endpoint with an access token.

```python
class TokenVerifier(Protocol):
    """Checks an ID token's signature and algorithm against the provider's published keys."""

    def verify(self, id_token: str) -> dict[str, Any]:
        """Return the claims of a token whose signature verifies; raise ``SignatureInvalidError`` or
        ``UnsupportedAlgorithmError`` otherwise. Claim checks (issuer, audience, ...) happen in the domain."""
```

`TokenVerifier` checks an ID token's signature and algorithm against the provider's published keys. Claim checks happen in the domain.

```python
class PendingLoginStore(Protocol):
    """Logins that have been started and not yet completed."""

    def put(self, pending: PendingLogin) -> None:
        """Remember a login attempt."""

    def pop(self, attempt_id: str) -> PendingLogin | None:
        """Remove and return the attempt: single use, so a replayed callback finds nothing."""
```

`PendingLoginStore`: `put` remembers an attempt; `pop` removes and returns it (single use, so a replayed callback finds nothing).

```python
class SessionStore(Protocol):
    """Signed-in sessions, keyed by the hash of the cookie value."""

    def add(self, session: UserSession) -> None:
        """Store a new session."""

    def get(self, session_id_hash: str) -> UserSession | None:
        """Fetch a session."""

    def replace(self, session: UserSession) -> None:
        """Overwrite a session (after a refresh or a touch)."""

    def delete(self, session_id_hash: str) -> UserSession | None:
        """Remove a session and return it, if it existed."""

    def count(self) -> int:
        """How many sessions are held."""

    def purge_inactive(self, now: datetime, idle: timedelta) -> int:
        """Drop sessions past their lifetime or idle longer than ``idle``; return how many."""
```

`SessionStore` keeps sessions keyed by the hash of the cookie value: `add`, `get`, `replace` (after a refresh or a touch), `delete` (returns the removed session), `count` and `purge_inactive` (drop sessions past their lifetime or idle too long).

```python
class Clock(Protocol):
    """Time, injected so tests are deterministic."""

    def now(self) -> datetime:
        """The current time, timezone-aware (UTC)."""
```

`Clock`: `now()` returns the current UTC time; injected so tests control time.

```python
class TokenGenerator(Protocol):
    """Unguessable values: state, nonce, PKCE verifier, session ids."""

    def token(self, nbytes: int = 32) -> str:
        """A URL-safe random string from ``nbytes`` of entropy."""
```

`TokenGenerator`: `token(nbytes=32)` returns a URL-safe random string from that many bytes of randomness, for the state, the nonce, the PKCE verifier and session ids.

### Line by line: `src/oidc_login/application/login_flow.py`

This file is the heart of the application. The **authorization code flow** works in two trips. First the app sends the browser to the identity provider (here Keycloak) with a request; the user signs in there, never on the app's own page; the provider sends the browser back to the app with a one-time **code**. Second, the app, server to server, trades the code for **tokens** (an access token, a refresh token and an ID token). The code is useless without the PKCE verifier and without the app's client credentials.

```python
"""The authorization code flow with PKCE, ID token validation, server-side sessions with refresh rotation, and sign-out
with revocation."""
```

The docstring lists what the file covers: the code flow with PKCE, ID token validation, server-side sessions with refresh rotation, and sign-out with revocation.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import hashlib
import hmac
import logging
import threading
from dataclasses import dataclass, replace
from datetime import timedelta
```

Imports: `hashlib`, `hmac` (timing-safe comparison), `logging`, `threading` (a lock), `dataclass` and `replace` (copy a frozen record with a change), and `timedelta`.

```python
from oidc_login.application.ports import (
    Clock,
    IdentityProvider,
    PendingLoginStore,
    SessionStore,
    TokenGenerator,
    TokenVerifier,
)
from oidc_login.domain.claims import Expectations, check_access_token_hash, check_id_token_claims
from oidc_login.domain.errors import LoginError, ProviderError, SessionNotFoundError, StateMismatchError
from oidc_login.domain.models import PendingLogin, TokenResponse, TokenSet, UserSession
from oidc_login.domain.pkce import challenge_for
from oidc_login.domain.scopes import requested_scope
```

Imports of the ports and the domain pieces the flow uses.

```python
_log = logging.getLogger("oidc_login.flow")
```

`_log` is the logger `oidc_login.flow`.

```python
@dataclass(frozen=True, slots=True)
class LoginConfig:
    """Everything the flow needs to know about this app and the provider."""

    issuer: str
    client_id: str
    allowed_extra_scopes: frozenset[str]
    pending_ttl_seconds: int = 600
    session_idle_seconds: int = 900
    session_absolute_seconds: int = 28800
    refresh_margin_seconds: int = 30
    clock_leeway_seconds: int = 30
```

`LoginConfig` holds the settings of the flow: the expected issuer and client id, the allow-list of extra scopes and five times in seconds: how long a started login stays valid (600), how long a session may be idle (900), its absolute lifetime (28,800, eight hours), how early before expiry the access token is refreshed (30) and the clock leeway for token checks (30).

```python
@dataclass(frozen=True, slots=True)
class StartedLogin:
    """Where to send the browser, and the id that goes in the short-lived login-attempt cookie."""

    authorization_url: str
    attempt_id: str
    max_age_seconds: int
```

`StartedLogin` is the result of starting: the address to send the browser to, the attempt id for the login-attempt cookie and that cookie's lifetime.

```python
@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session and the raw cookie value, which exists on the server only at this moment."""

    raw_session_id: str
    session: UserSession
    max_age_seconds: int
```

`IssuedSession` is a new session with the raw cookie value, which exists on the server only at this moment, and its lifetime.

```python
def hash_session_id(raw_session_id: str) -> str:
    """The stored form of a session cookie value."""
    return hashlib.sha256(raw_session_id.encode()).hexdigest()
```

`hash_session_id` is the stored form of a session cookie value: its SHA-256 in hexadecimal. A database or memory dump then holds no usable cookie value.

```python
class LoginService:
    """Starts and completes sign-in, and manages the session afterwards. No HTTP and no HTTP client in here."""
```

`LoginService` starts and completes sign-in and manages the session afterwards. It contains no HTTP and no HTTP client.

```python
    def __init__(
        self,
        provider: IdentityProvider,
        verifier: TokenVerifier,
        pending: PendingLoginStore,
        sessions: SessionStore,
        clock: Clock,
        tokens: TokenGenerator,
        config: LoginConfig,
    ) -> None:
        self._provider = provider
        self._verifier = verifier
        self._pending = pending
        self._sessions = sessions
        self._clock = clock
        self._tokens = tokens
        self._config = config
```

The constructor receives the provider, the token verifier, the two stores, the clock, the token generator and the config (dependency injection) and keeps them.

```python
        # One refresh at a time: two concurrent refreshes with the same rotating token would burn it.
        # ponytail: a single lock is enough for one process; a shared store needs a per-session lock there.
        self._refresh_lock = threading.Lock()
```

A `threading.Lock` makes only one refresh happen at a time. The comment explains why: two concurrent refreshes with the same rotating refresh token would burn it (the second use would be seen as reuse and the provider would revoke the family). The `ponytail:` comment notes the limit: one lock is enough for one process; a shared store would need a per-session lock.

```python
    def start(self, extra_scopes: list[str]) -> StartedLogin:
        """Begin a login: fresh state, nonce and PKCE verifier; only the challenge goes to the provider."""
```

`start` begins a login with a fresh state, nonce and PKCE verifier; only the challenge goes to the provider.

```python
        verifier = self._tokens.token(64)
        pending = PendingLogin(
            attempt_id=self._tokens.token(),
            state=self._tokens.token(),
            nonce=self._tokens.token(),
            code_verifier=verifier,
            scope=requested_scope(extra_scopes, self._config.allowed_extra_scopes),
            created_at=self._clock.now(),
        )
```

The verifier is 64 random bytes of token. The pending record gets a random attempt id, a random **state** (a value the provider echoes back, which proves the callback answers a login this app started; it defends against cross-site request forgery on the callback), a random **nonce** (a value that will appear inside the ID token, tying the token to this login) and the scope built from the allow-list.

```python
        self._pending.put(pending)
        url = self._provider.authorization_url(
            state=pending.state, nonce=pending.nonce, code_challenge=challenge_for(verifier), scope=pending.scope
        )
```

The attempt is stored, and the provider builds the authorization address from the state, nonce, the S256 challenge and the scope. The verifier itself is not sent.

```python
        _log.info("login started", extra={"event": "login.started", "scope": pending.scope})
        return StartedLogin(url, pending.attempt_id, self._config.pending_ttl_seconds)
```

A log line `login started` (the scope only, no secrets) and a `StartedLogin` with the pending lifetime.

```python
    def complete(self, *, attempt_id: str | None, state: str | None, code: str | None) -> IssuedSession:
        """Finish a login from the callback.

        Raises ``StateMismatchError`` unless the callback belongs to a login this browser started and has not
        finished yet; ``ProviderError`` when the provider refuses the code; ``TokenValidationError`` (a subclass
        per check) when the ID token is not acceptable.
        """
```

`complete` finishes a login from the callback. The docstring lists the errors: a state mismatch unless the callback belongs to a login this browser started and has not finished; a provider error when the provider refuses the code; a token validation error per failed check.

```python
        pending = self._claim_attempt(attempt_id, state)
        if not code:
            raise StateMismatchError("the callback carries no authorization code")
```

`_claim_attempt` checks the attempt and the state and removes the attempt (single use). A callback without a code is also a state mismatch.

```python
        response = self._provider.exchange_code(code=code, code_verifier=pending.code_verifier)
        if response.id_token is None:
            raise ProviderError("invalid_response", "the token response has no ID token")
```

The code and the PKCE verifier are traded for tokens. A response without an ID token is a `ProviderError`.

```python
        claims = self._verifier.verify(response.id_token)
```

The signature is verified first, giving the claims.

```python
        now = self._clock.now()
        identity = check_id_token_claims(
            claims,
            Expectations(
                issuer=self._config.issuer,
                client_id=self._config.client_id,
                nonce=pending.nonce,
                now=now,
                leeway=timedelta(seconds=self._config.clock_leeway_seconds),
            ),
        )
```

Then the claims are checked against what this attempt expects: the issuer, the client id, the nonce, the current time and the leeway. The identity comes out.

```python
        check_access_token_hash(claims, response.access_token)
```

If the ID token has `at_hash`, the access token must match it.

```python
        raw_session_id = self._tokens.token()
        session = UserSession(
            session_id_hash=hash_session_id(raw_session_id),
            identity=identity,
            tokens=self._token_set(response, previous=None),
            csrf_token=self._tokens.token(),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=self._config.session_absolute_seconds),
        )
```

A random raw session id and a new session are built: the hashed id, the identity, the token set, a random CSRF token, the times and the absolute expiry.

```python
        self._sessions.purge_inactive(now, timedelta(seconds=self._config.session_idle_seconds))
        self._sessions.add(session)
```

Inactive sessions are purged and the new one is added.

```python
        _log.info("login completed", extra={"event": "login.completed", "subject": identity.subject})
        return IssuedSession(raw_session_id, session, self._config.session_absolute_seconds)
```

A log line `login completed` with the subject, and the issued session is returned.

```python
    def resolve(self, raw_session_id: str | None) -> UserSession | None:
        """The live session for a cookie value, or ``None`` when unknown, idle too long or past its lifetime."""
        if not raw_session_id:
            return None
```

`resolve` returns the live session for a cookie value or `None`. No value means no session.

```python
        key = hash_session_id(raw_session_id)
        session = self._sessions.get(key)
        if session is None:
            return None
```

The value is hashed and looked up; unknown gives `None`.

```python
        now = self._clock.now()
        idle_limit = session.last_seen_at + timedelta(seconds=self._config.session_idle_seconds)
        if now >= session.expires_at or now >= idle_limit:
            self._sessions.delete(key)
            return None
```

The session is dead if now is past its absolute expiry or past its idle limit; a dead session is deleted.

```python
        touched = replace(session, last_seen_at=now)
        self._sessions.replace(touched)
        return touched
```

A live session is "touched": a copy with the last-seen time set to now replaces the stored one and is returned.

```python
    def refresh(self, session: UserSession) -> UserSession:
        """Rotate the tokens: the provider issues a new refresh token and the old one stops working.

        The session is dropped and the error raised when the provider refuses (the refresh token was revoked,
        reused or expired): the user has to sign in again.
        """
```

`refresh` rotates the tokens: the provider issues a new refresh token and the old one stops working. If the provider refuses (revoked, reused or expired), the session is dropped and the error raised; the user has to sign in again.

```python
        with self._refresh_lock:
            current = self._sessions.get(session.session_id_hash)
            if current is None:
                raise SessionNotFoundError("session ended")
            refresh_token = current.tokens.refresh_token
            if refresh_token is None:
                raise SessionNotFoundError("session has no refresh token")
```

Under the lock, the stored session is fetched fresh. A missing session or one without a refresh token raises `SessionNotFoundError`.

```python
            try:
                response = self._provider.refresh(refresh_token)
            except LoginError:
                self._sessions.delete(current.session_id_hash)
                _log.warning("refresh refused, session dropped", extra={"event": "token.refresh_failed"})
                raise
```

The provider is asked to refresh. Any `LoginError` deletes the session, logs a warning and re-raises.

```python
            renewed = replace(current, tokens=self._token_set(response, previous=current.tokens))
            self._sessions.replace(renewed)
            _log.info("tokens refreshed", extra={"event": "token.refreshed", "subject": current.identity.subject})
            return renewed
```

The new tokens are built (keeping old values where the response omits them), the session is replaced and the renewed session is returned.

```python
    def access_token(self, session: UserSession) -> tuple[str, UserSession]:
        """An access token good for at least the refresh margin, refreshing first when it is about to expire."""
        margin = timedelta(seconds=self._config.refresh_margin_seconds)
        if self._clock.now() + margin >= session.tokens.access_expires_at:
            session = self.refresh(session)
        return session.tokens.access_token, session
```

`access_token` returns an access token that is good for at least the refresh margin, refreshing first if the current one is about to expire, along with the possibly renewed session.

```python
    def sign_out(self, raw_session_id: str | None) -> bool:
        """End the session here, then revoke the refresh token at the provider. Returns whether the provider
        confirmed the revocation; the local session is gone either way."""
```

`sign_out` ends the session here and then revokes the refresh token at the provider. It returns whether the provider confirmed; the local session is gone either way.

```python
        if not raw_session_id:
            return False
        session = self._sessions.delete(hash_session_id(raw_session_id))
        if session is None or session.tokens.refresh_token is None:
            return False
```

No cookie value, an unknown session or one with no refresh token returns `False`.

```python
        try:
            self._provider.revoke(session.tokens.refresh_token)
        except LoginError:
            _log.warning("revocation failed at sign out", extra={"event": "logout.revoke_failed"})
            return False
        _log.info("signed out", extra={"event": "logout", "subject": session.identity.subject, "revoked": True})
        return True
```

The provider is asked to revoke. A failure is logged and returns `False`; success logs `signed out` with `revoked: True` and returns `True`.

```python
    @staticmethod
    def csrf_valid(session: UserSession, supplied: str | None) -> bool:
        """Constant-time comparison of the supplied CSRF token with the session's."""
        return supplied is not None and hmac.compare_digest(session.csrf_token.encode(), supplied.encode())
```

`csrf_valid` compares the supplied CSRF token with the session's in constant time; a missing token is invalid.

```python
    def _claim_attempt(self, attempt_id: str | None, state: str | None) -> PendingLogin:
        if not attempt_id or not state:
            raise StateMismatchError("the callback is not tied to a login this browser started")
```

`_claim_attempt` first requires both the attempt id (from the login-attempt cookie) and the state (from the address).

```python
        pending = self._pending.pop(attempt_id)
        if pending is None:
            raise StateMismatchError("unknown or already used login attempt")
```

The attempt is removed from the store with `pop`. An unknown or already used attempt is refused, so a replayed callback fails.

```python
        if not hmac.compare_digest(pending.state.encode(), state.encode()):
            raise StateMismatchError("state does not match the login this browser started")
```

The returned state must equal the stored one (constant-time comparison).

```python
        if self._clock.now() >= pending.created_at + timedelta(seconds=self._config.pending_ttl_seconds):
            raise StateMismatchError("the login attempt expired")
        return pending
```

An attempt older than the pending lifetime is refused as expired; otherwise it is returned.

```python
    def _token_set(self, response: TokenResponse, *, previous: TokenSet | None) -> TokenSet:
        return TokenSet(
            access_token=response.access_token,
            refresh_token=response.refresh_token or (previous.refresh_token if previous else None),
            id_token=response.id_token or (previous.id_token if previous else ""),
            access_expires_at=self._clock.now() + timedelta(seconds=response.expires_in),
            scope=response.scope or (previous.scope if previous else ""),
        )
```

`_token_set` builds a `TokenSet` from a response. When a refresh response omits the refresh token, the ID token or the scope, the previous values are kept. The access expiry is now plus `expires_in` seconds.

### Line by line: `src/oidc_login/infrastructure/memory_stores.py`

```python
"""In-memory stores for pending logins and sessions.

The tokens in a session never touch a disk or a database, which is a feature here. The price is that the state belongs
to one process: run one worker with several threads, and a restart signs everyone out. The ports are five short
methods each; a Redis adapter is the way to scale out (see ARCHITECTURE.md).
"""
```

The docstring: in-memory stores for pending logins and sessions. The tokens in a session never touch a disk or a database, which is a feature here. The price is that the state belongs to one process: run one worker with several threads, and a restart signs everyone out. The ports are five short methods each, so a Redis adapter is the way to scale out (see `ARCHITECTURE.md`).

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import threading
from datetime import datetime, timedelta

from oidc_login.application.ports import Clock
from oidc_login.domain.models import PendingLogin, UserSession
```

Imports: `threading` (locks), time types, the clock port and the records.

```python
MAX_PENDING = 10_000
```

`MAX_PENDING` is 10,000.

```python
class InMemoryPendingLoginStore:
    """Single-use, time-limited login attempts, bounded in number so a flood of ``/login`` cannot fill memory."""
```

`InMemoryPendingLoginStore` keeps single-use, time-limited login attempts, bounded in number so a flood of requests to `/login` cannot fill memory.

```python
    def __init__(self, clock: Clock, ttl_seconds: int, max_entries: int = MAX_PENDING) -> None:
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max = max_entries
        self._items: dict[str, PendingLogin] = {}
        self._lock = threading.Lock()
```

The constructor takes the clock, the lifetime and a maximum count, and creates an empty dictionary and a lock. A **lock** lets only one thread at a time run the code inside `with self._lock:`; the server runs several threads, and a dictionary changed by two threads at once could be corrupted.

```python
    def put(self, pending: PendingLogin) -> None:
        """Remember an attempt; expired ones are dropped first, then the oldest if the store is still full."""
        with self._lock:
            now = self._clock.now()
            for key in [k for k, item in self._items.items() if item.created_at + self._ttl <= now]:
                del self._items[key]
            while len(self._items) >= self._max:
                del self._items[next(iter(self._items))]
            self._items[pending.attempt_id] = pending
```

`put` first removes expired attempts (the list comprehension collects their keys before deleting, because a dictionary cannot be changed while looping over it), then, while the store is full, removes the oldest (dictionaries keep insertion order, so `next(iter(...))` is the oldest key), then stores the new attempt.

```python
    def pop(self, attempt_id: str) -> PendingLogin | None:
        """Remove and return the attempt (single use)."""
        with self._lock:
            return self._items.pop(attempt_id, None)
```

`pop` removes and returns the attempt, or `None`. Removing it is what makes a callback single-use.

```python
class InMemorySessionStore:
    """Sessions by the hash of their cookie value."""

    def __init__(self) -> None:
        self._items: dict[str, UserSession] = {}
        self._lock = threading.Lock()
```

`InMemorySessionStore` keeps sessions by the hash of their cookie value, with a lock.

```python
    def add(self, session: UserSession) -> None:
        """Store a session."""
        with self._lock:
            self._items[session.session_id_hash] = session
```

`add` stores a session.

```python
    def get(self, session_id_hash: str) -> UserSession | None:
        """Fetch a session."""
        with self._lock:
            return self._items.get(session_id_hash)
```

`get` fetches one.

```python
    def replace(self, session: UserSession) -> None:
        """Overwrite a session that still exists; a session deleted in the meantime stays deleted."""
        with self._lock:
            if session.session_id_hash in self._items:
                self._items[session.session_id_hash] = session
```

`replace` overwrites only if the session still exists, so a session deleted in the meantime (for example by sign-out during a refresh) stays deleted.

```python
    def delete(self, session_id_hash: str) -> UserSession | None:
        """Remove and return a session."""
        with self._lock:
            return self._items.pop(session_id_hash, None)
```

`delete` removes and returns a session.

```python
    def purge_inactive(self, now: datetime, idle: timedelta) -> int:
        """Drop sessions past their lifetime or idle longer than ``idle``."""
        with self._lock:
            stale = [k for k, s in self._items.items() if now >= s.expires_at or now >= s.last_seen_at + idle]
            for key in stale:
                del self._items[key]
            return len(stale)
```

`purge_inactive` collects the sessions that are past their absolute expiry or idle longer than the idle time, deletes them and returns how many.

```python
    def count(self) -> int:
        """How many sessions are held."""
        with self._lock:
            return len(self._items)
```

`count` returns how many sessions are held.

### Line by line: `src/oidc_login/infrastructure/clock.py`

```python
"""System clock and random source."""

from __future__ import annotations
```

The docstring and the type-hint line.

```python
import secrets
from datetime import UTC, datetime
```

`secrets` is the standard module for security-grade randomness, and `datetime` with `UTC` gives time-zone-aware times.

```python
class SystemClock:
    """The real time, in UTC."""

    def now(self) -> datetime:
        """The current UTC time."""
        return datetime.now(UTC)
```

`SystemClock.now()` returns the current UTC time (the `Clock` port).

```python
class SecretsTokenGenerator:
    """Random values from the operating system's CSPRNG."""

    def token(self, nbytes: int = 32) -> str:
        """A URL-safe token; ``nbytes=64`` gives an 86-character PKCE verifier."""
        return secrets.token_urlsafe(nbytes)
```

`SecretsTokenGenerator.token(nbytes)` returns `secrets.token_urlsafe(nbytes)`: that many random bytes from the operating system's cryptographic random source, as URL-safe text. 64 bytes give an 86-character PKCE verifier, within the 43 to 128 the standard allows.

### Line by line: `src/oidc_login/infrastructure/logging.py`

```python
"""Structured (JSON) logging with redaction, so a token that reaches a log call never reaches the log."""
```

The docstring: structured JSON logging with redaction, so a token that reaches a log call never reaches the log.

```python
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any
```

Imports: `json`, `logging`, `re`, `sys`, `datetime` with `UTC`, `Any`.

```python
REDACTED = "[redacted]"
_SENSITIVE_KEY = re.compile(
    r"pass(word|wd)?|secret|token|cookie|authorization|csrf|session|api[_-]?key|code|verifier|nonce|state",
    re.IGNORECASE,
)
```

`REDACTED` is the replacement text. `_SENSITIVE_KEY` is a case-insensitive regular expression matching field names that suggest a secret: `pass`, `password`, `passwd`, `secret`, `token`, `cookie`, `authorization`, `csrf`, `session`, `api_key`, `code`, `verifier`, `nonce` and `state`. The last four are particular to this flow: the authorization code, the PKCE verifier, the nonce and the state must not be logged either.

```python
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}
```

`_RESERVED` is the set of attribute names every `LogRecord` already has, plus `message` and `asctime`; anything else was added by the caller through `extra=`.

```python
def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace the value of every field whose name looks sensitive (tokens, codes, secrets, cookies)."""
    return {key: REDACTED if _SENSITIVE_KEY.search(key) else value for key, value in fields.items()}
```

`redact` returns a new dictionary with the values of sensitive-looking keys replaced.

```python
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
```

`JsonFormatter.format` builds a dictionary with the time (ISO 8601, milliseconds), level, logger name and message, adds the caller's extra fields after redaction, adds the stack trace under `exception` if there is one, and returns compact JSON.

```python
def configure_logging(level: str) -> None:
    """Send every log record to standard error as JSON at the given level."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
```

`configure_logging` makes a handler that writes to standard error with the JSON formatter, makes it the root logger's only handler and sets the level.

### Line by line: `src/oidc_login/interfaces/composition.py`

```python
"""The composition root: the one place that knows which adapter implements which port."""
```

The docstring: the **composition root**, the one place that knows which adapter implements which port.

```python
from __future__ import annotations

from dataclasses import dataclass
```

Type hints kept as text and `dataclass`.

```python
from oidc_login.application.login_flow import LoginConfig, LoginService
from oidc_login.infrastructure.clock import SecretsTokenGenerator, SystemClock
from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
from oidc_login.infrastructure.oidc_provider import OidcProvider
from oidc_login.infrastructure.settings import Settings
```

Imports of the flow, the clock and token generator, the verifier, the two stores, the provider adapter and the settings. This is the one file that may import both sides.

```python
@dataclass(frozen=True, slots=True)
class Container:
    """The wired application."""

    settings: Settings
    provider: OidcProvider
    flow: LoginService
    sessions: InMemorySessionStore
```

`Container` is a frozen record of the wired application: settings, the provider, the login service and the session store.

```python
def build_container(settings: Settings) -> Container:
    """Wire the provider adapter, the verifier, the in-memory stores and the flow."""
```

`build_container` wires everything from the settings.

```python
    clock = SystemClock()
    provider = OidcProvider(
        issuer=settings.issuer,
        discovery_base=settings.discovery_base,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.redirect_uri,
        timeout_seconds=settings.http_timeout_seconds,
    )
```

The clock, then the provider with the issuer, the discovery base, the client id and secret, the redirect address and the timeout.

```python
    sessions = InMemorySessionStore()
    flow = LoginService(
        provider=provider,
        verifier=JwksTokenVerifier(provider.jwks),
        pending=InMemoryPendingLoginStore(clock, settings.pending_ttl_seconds),
        sessions=sessions,
        clock=clock,
        tokens=SecretsTokenGenerator(),
```

The session store, then the login service: the provider, a verifier whose key source is the provider's `jwks` method, a pending store with the configured lifetime, the sessions, the clock and a random token generator.

```python
        config=LoginConfig(
            issuer=settings.issuer,
            client_id=settings.client_id,
            allowed_extra_scopes=settings.allowed_extra_scopes,
            pending_ttl_seconds=settings.pending_ttl_seconds,
            session_idle_seconds=settings.session_idle_seconds,
            session_absolute_seconds=settings.session_absolute_seconds,
            refresh_margin_seconds=settings.refresh_margin_seconds,
        ),
```

`LoginConfig` carries the issuer, client id, scope allow-list and the five times from the settings.

```python
    )
    return Container(settings=settings, provider=provider, flow=flow, sessions=sessions)
```

The container is returned.

### Line by line: `src/oidc_login/interfaces/health_cli.py`

```python
"""``oidc-login-health``: exit 0 when the running app answers ``/healthz`` (the container's health check).

Liveness only: the app being up does not depend on the provider being up. ``/readyz`` adds the provider check.
"""
```

The docstring: the command `oidc-login-health` exits 0 when the running app answers `/healthz`; the container's health check runs it. It checks liveness only: the app being up does not depend on the provider being up. `/readyz` adds the provider check.

```python
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
```

Type hints kept as text; imports of `os`, `sys` and the standard URL tools.

```python
def main() -> int:
    """Probe the liveness endpoint on the loopback address; print the outcome and return the exit code."""
    port = os.environ.get("APP_PORT", "3000")
    url = f"http://127.0.0.1:{port}/healthz"
```

`main` reads the port from `APP_PORT` (default 3000) and builds the address on `127.0.0.1`, the loopback address that always means "this same machine".

```python
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            ok = response.status == 200
```

It opens the address with a three-second limit and records whether the status was 200.

```python
    except (urllib.error.URLError, OSError) as error:
        print(f"unhealthy: {error}", file=sys.stderr)
        return 1
```

A network error prints `unhealthy: <reason>` to standard error and returns 1.

```python
    print("healthy" if ok else "unhealthy")
    return 0 if ok else 1
```

Otherwise it prints `healthy` or `unhealthy` and returns 0 or 1.

```python
if __name__ == "__main__":
    sys.exit(main())
```

When run as a program, the return value is the exit code.

### Line by line: `src/oidc_login/interfaces/demo_cli.py`

```python
"""``oidc-login-demo``: the lesson's scenario against the running provider, printed as checked steps.

The app runs in-process (the same Flask app and the same adapters as in production, over the Flask test client) so the
demo can show what only the server sees: the tokens it holds, the refresh token before and after rotation. The users
are scripted browsers; passwords come from the environment and are never printed.
"""
```

The docstring: the command `oidc-login-demo` runs the lesson's scenario against the running provider and prints each check. The app runs inside the same process (the same Flask app and adapters as production, driven through Flask's test client), so the demo can show what only the server sees: the tokens it holds and the refresh token before and after rotation. The users are scripted browsers; passwords come from the environment and are never printed.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import argparse
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
```

Imports: `argparse`, `os`, `sys`, `Callable` and `Mapping`, `dataclass` and `replace` (a copy of a frozen record with changes), `timedelta`, and URL helpers: `parse_qs` (turns query text into a dictionary of lists), `urlencode` and `urlsplit`.

```python
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
```

`httpx` (an HTTP client, `tech/httpx.md`), `jwt` (PyJWT, to forge tokens) and an RSA key generator from the `cryptography` package.

```python
from oidc_login.domain.claims import Expectations, check_id_token_claims
from oidc_login.domain.errors import LoginError, ProviderError, TokenValidationError
from oidc_login.domain.models import UserSession
from oidc_login.domain.pkce import challenge_for
from oidc_login.infrastructure.clock import SystemClock
from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier
from oidc_login.infrastructure.settings import Settings
from oidc_login.interfaces.composition import Container, build_container
from oidc_login.interfaces.http.app import create_app
from oidc_login.interfaces.http.security import LOGIN_COOKIE, SESSION_COOKIE
from oidc_login.interfaces.scripted_browser import AppBrowser, ProviderBrowser
```

Imports of the domain checks, the errors, the session record, the PKCE helper, the clock, the verifier, the settings, the container builder, the Flask app, the cookie names and the two scripted browsers.

```python
DEMO_USERNAME = "demo-user"
SPA_CLIENT_ID = "notes-spa"
SPA_REDIRECT_URI = "http://localhost:3001/callback"
```

Constants: the demo user's name `demo-user`, and the id and redirect address of a second, **public** client `notes-spa` (a client that cannot keep a secret, such as a browser app) registered in the realm.

```python
@dataclass(frozen=True, slots=True)
class Step:
    """One checked claim of the scenario."""

    name: str
    passed: bool
    detail: str
```

`Step` is one checked claim: name, whether it passed and a detail text.

```python
def _step(name: str, passed: bool, detail: str) -> Step:
    return Step(name, passed, detail)
```

`_step` builds a `Step`.

```python
def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
```

`_query` returns the query of an address as a dictionary of first values.

```python
def _cookie_attributes(set_cookie_headers: list[str], name: str) -> tuple[str, str]:
    cookie = next((header for header in set_cookie_headers if header.startswith(f"{name}=")), "")
    value = cookie.split("=", 1)[1].split(";", 1)[0] if cookie else ""
    return value, "; ".join(part.strip() for part in cookie.split(";")[1:])
```

`_cookie_attributes` finds the `Set-Cookie` header of a given cookie name and returns its value and the attribute text after it.

```python
class Scenario:
    """The scenario's moving parts and one method per claim. Each method returns a ``Step`` and never raises on a
    failed expectation; the tests call the same methods and assert on the result."""
```

`Scenario` holds the moving parts, one method per claim. Each method returns a `Step` and never raises on a failed expectation; the tests call the same methods.

```python
    def __init__(self, env: Mapping[str, str]) -> None:
        self.settings = Settings.from_environment(env)
        self.container: Container = build_container(self.settings)
        self.app = create_app(self.container)
        self.password = env.get("DEMO_USER_PASSWORD", "")
        self.user = ProviderBrowser(DEMO_USERNAME, self.password)
```

The constructor validates settings from the environment, builds the container and the Flask app, reads the demo password from `DEMO_USER_PASSWORD` and creates the scripted provider-side browser.

```python
    def close(self) -> None:
        """Release the HTTP clients."""
        self.user.close()
        self.container.provider.close()
```

`close` releases the HTTP clients.

```python
    def server_session(self) -> UserSession:
        """The session the server created most recently (the demo signs in one browser at a time)."""
        sessions = list(self.container.sessions._items.values())
        if not sessions:
            raise RuntimeError("the server holds no session")
        return max(sessions, key=lambda session: session.created_at)
```

`server_session` returns the most recently created session in the in-memory store (the demo signs in one browser at a time), or raises if there is none. It reads the store's private dictionary directly: the demo needs to look inside the server, which no route allows.

```python
    def new_browser(self) -> AppBrowser:
        """A fresh browser with no cookies."""
        return AppBrowser(self.app)
```

`new_browser` returns a fresh browser with no cookies.

```python
    def authorize_code(self, *, client_id: str, redirect_uri: str, verifier: str) -> str:
        """Get an authorization code for any client from the provider, the way a browser would."""
        url = self.container.provider.authorization_url(
            state="demo-state", nonce="demo-nonce", code_challenge=challenge_for(verifier), scope="openid"
        )
        url = _replace_query_value(_replace_query_value(url, "client_id", client_id), "redirect_uri", redirect_uri)
        hop = self.user.authorize(url)
        if hop.location is None:
            raise RuntimeError(f"no authorization code: provider answered {hop.status}")
        return _query(hop.location)["code"]
```

`authorize_code` gets an authorization code for any client the way a browser would: it builds an authorization address, replaces the client id and redirect address, lets the scripted user authorize it at the provider, and reads the `code` from the redirect.

```python
    def discovery(self) -> Step:
        """The provider's discovery document and keys are reachable."""
        provider = self.container.provider
        metadata = provider.metadata()
        keys = provider.jwks().get("keys", [])
        usable = isinstance(keys, list) and len(keys) >= 1
        return _step(
            "the provider's discovery document and signing keys are reachable",
            usable and metadata.issuer == self.settings.issuer,
            f"issuer {metadata.issuer}; {len(keys)} signing keys at {metadata.jwks_uri}",
        )
```

Step 1, `discovery`: the discovery document and the signing keys are reachable, the issuer matches, and at least one key exists.

```python
    def start_login(self, browser: AppBrowser, scope: str | None = None) -> tuple[Step, str]:
        """The app sends the browser to the provider with state, nonce and an S256 challenge."""
        response = browser.get("/login" + (f"?scope={scope}" if scope else ""))
        location = response.headers.get("Location", "")
        query = _query(location)
        value, attributes = _cookie_attributes(response.headers.getlist("Set-Cookie"), LOGIN_COOKIE)
```

Step 2, `start_login`: opens `/login` and reads the redirect and the login-attempt cookie.

```python
        checks = {
            "response_type=code": query.get("response_type") == "code",
            "S256 challenge": query.get("code_challenge_method") == "S256"
            and len(query.get("code_challenge", "")) == 43,
            "state": len(query.get("state", "")) >= 32,
            "nonce": len(query.get("nonce", "")) >= 32,
            "exact redirect_uri": query.get("redirect_uri") == self.settings.redirect_uri,
            "no client secret in the URL": self.settings.client_secret not in location and "client_secret" not in query,
            "no verifier in the URL": "code_verifier" not in query,
            "attempt cookie HttpOnly Secure SameSite=Lax": all(
                a in attributes for a in ("HttpOnly", "Secure", "SameSite=Lax")
            )
            and bool(value),
        }
```

Eight checks on that redirect: `response_type=code`; an S256 challenge of 43 characters (the base64url of 32 bytes); a state and a nonce of at least 32 characters; the exact registered redirect address; no client secret in the address; no verifier in the address; and an attempt cookie that is HttpOnly, Secure and SameSite=Lax and not empty.

```python
        missing = [name for name, ok in checks.items() if not ok]
        detail = f"redirect to {urlsplit(location).path}: " + ", ".join(checks) if not missing else f"failed: {missing}"
        return _step(
            "the app sends the browser to the provider with state, nonce and an S256 challenge", not missing, detail
        ), location
```

The names of failed checks are collected; the detail lists all checks if all passed, or the failed ones. The step and the address are returned.

```python
    def authenticate(self, location: str) -> tuple[Step, str]:
        """The user signs in at the provider; it redirects to the registered URI with a code and the same state."""
        hop = self.user.authorize(location)
        back = hop.location or ""
        ok = back.startswith(self.settings.redirect_uri + "?") and {"code", "state"} <= set(_query(back))
        same_state = _query(back).get("state") == _query(location).get("state")
        return (
            _step(
                "the user authenticates at the provider and is redirected to the one registered URI",
                ok and same_state,
                f"provider answered {hop.status}, redirect to {urlsplit(back).path} with code and the same state",
            ),
            back,
        )
```

`authenticate`: the user signs in at the provider; it must redirect to the registered address with a `code` and a `state`, and the state must be the one the app sent.

```python
    def complete_login(self, browser: AppBrowser, callback_location: str) -> Step:
        """The callback exchanges the code on the server and starts an opaque session."""
        response = browser.follow_callback(callback_location)
        value, attributes = _cookie_attributes(response.headers.getlist("Set-Cookie"), SESSION_COOKIE)
        if not self.container.sessions.count():
            return _step(
                "the code is exchanged on the server and the browser gets only an opaque session cookie",
                False,
                f"callback -> {response.status_code}: no session was created",
            )
```

`complete_login`: follows the callback. If the store holds no session, the step fails at once.

```python
        session = self.server_session()
        held = [session.tokens.access_token, session.tokens.refresh_token or "", session.tokens.id_token]
        pages = [response, browser.get("/"), browser.get("/me")]
        blob = "".join(page.get_data(as_text=True) + str(dict(page.headers)) for page in pages) + callback_location
        leaked = [index for index, token in enumerate(held) if token and token in blob]
```

It reads the server's session, lists the three tokens the server holds, collects the callback response, the home page and the `/me` page and the callback address as one text, and finds any token that appears in it.

```python
        ok = (
            response.status_code == 302
            and all(a in attributes for a in ("HttpOnly", "Secure", "SameSite=Lax"))
            and value.count(".") == 0
            and len(value) >= 40
            and not leaked
        )
```

Passing needs: a 302 redirect, a cookie with the three attributes, a value with no dots (not a JWT) and at least 40 characters (opaque), and no leaked token.

```python
        detail = (
            f"callback -> {response.status_code}; cookie {SESSION_COOKIE}=<{len(value)} opaque characters> "
            f"({attributes}); "
            f"server holds access, refresh and ID tokens; none appears in a URL, header or page"
        )
        return _step(
            "the code is exchanged on the server and the browser gets only an opaque session cookie", ok, detail
        )
```

The detail says the browser has a cookie of N opaque characters and that none of the server's tokens appears in a URL, header or page.

```python
    def id_token_validation(self) -> Step:
        """The validator rejects a wrong audience, an expired token, a wrong key, algorithm none and a wrong nonce."""
        session = self.server_session()
        token = session.tokens.id_token
        provider = self.container.provider
        verifier = JwksTokenVerifier(provider.jwks)
        claims = verifier.verify(token)
        now = SystemClock().now()
        good = Expectations(self.settings.issuer, self.settings.client_id, str(claims.get("nonce")), now)
        check_id_token_claims(claims, good)  # the real token passes
```

Step `id_token_validation`: takes the real ID token, verifies it, and checks its claims with correct expectations (they pass).

```python
        header = jwt.get_unverified_header(token)

        forger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(claims, forger, algorithm="RS256", headers={"kid": header["kid"]})
        unsigned = jwt.encode(claims, key="", algorithm="none", headers={"kid": header["kid"]})
```

It builds two forgeries from the real claims: one signed with a brand-new RSA key (a **wrong key**) but carrying the real `kid`, and one with the algorithm `none` (**unsigned**).

```python
        outcomes: list[tuple[str, str]] = []

        def attempt(label: str, action: Callable[[], object]) -> None:
            try:
                action()
            except TokenValidationError as error:
                outcomes.append((label, error.reason))
            else:
                outcomes.append((label, "ACCEPTED"))
```

`attempt` runs an action and records the reason of the validation error, or `ACCEPTED` if nothing was raised.

```python
        attempt("wrong audience", lambda: check_id_token_claims(claims, replace(good, client_id="some-other-client")))
        attempt("expired", lambda: check_id_token_claims(claims, replace(good, now=now + timedelta(days=1))))
        attempt("wrong key", lambda: verifier.verify(forged))
        attempt("none algorithm", lambda: verifier.verify(unsigned))
        attempt("wrong nonce", lambda: check_id_token_claims(claims, replace(good, nonce="another-logins-nonce")))
```

Five attempts: a wrong audience; an expired token (time moved one day on); the forged signature; the `none` algorithm; and a wrong nonce.

```python
        expected = {
            "wrong audience": "audience claim does not match client id",
            "expired": "token has expired",
            "wrong key": "signature verification failed",
            "none algorithm": "signing algorithm 'none' is not accepted",
            "wrong nonce": "nonce mismatch: possible token substitution",
        }
        ok = dict(outcomes) == expected
```

The expected reasons are listed and the step passes only if each attempt failed with exactly its own reason.

```python
        return _step(
            "the ID token validator rejects five bad tokens, each for its own reason",
            ok,
            "; ".join(f"{k} -> {v}" for k, v in outcomes),
        )
```

The step is returned with the five outcomes in its detail.

```python
    def mismatched_state(self) -> Step:
        """A callback whose state is not the one this browser's login sent is refused."""
        browser = self.new_browser()
        _, location = self.start_login(browser)
        _, back = self.authenticate(location)
        tampered = back.replace(f"state={_query(back)['state']}", "state=attacker-chosen-state")
        status = browser.follow_callback(tampered).status_code
        return _step(
            "a callback with a mismatched state is refused",
            status == 400 and browser.cookie(SESSION_COOKIE) is None,
            f"GET /callback with a changed state -> {status}",
        )
```

`mismatched_state`: a new browser logs in, the callback address gets its state replaced by `attacker-chosen-state`, and the callback must answer 400 with no session cookie.

```python
    def login_csrf(self) -> Step:
        """A callback from a browser that did not start the login is refused (login CSRF)."""
        attacker, victim = self.new_browser(), self.new_browser()
        _, location = self.start_login(attacker)
        _, back = self.authenticate(location)
        status = victim.follow_callback(
            back
        ).status_code  # the attacker's valid code and state, in the victim's browser
        return _step(
            "a callback from a browser that did not start the login is refused",
            status == 400 and victim.cookie(SESSION_COOKIE) is None,
            f"the attacker's own code and state in another browser -> {status}",
        )
```

`login_csrf`: the attacker starts a login in one browser and gets a valid code and state; the victim's browser follows that callback. It must answer 400 and set no session: the attempt cookie belongs to the attacker's browser.

```python
    def replayed_callback(self) -> Step:
        """A callback that already succeeded cannot be replayed."""
        browser = self.new_browser()
        _, location = self.start_login(browser)
        _, back = self.authenticate(location)
        first = browser.follow_callback(back).status_code
        again = browser.follow_callback(back).status_code
        return _step(
            "a callback cannot be replayed", first == 302 and again == 400, f"first use -> {first}, replay -> {again}"
        )
```

`replayed_callback`: the first use of a callback gives 302, the replay gives 400.

```python
    def lookalike_redirect_uri(self) -> Step:
        """The provider refuses a redirect URI that is not exactly the registered one, before the app sees anything."""
        browser = self.new_browser()
        _, location = self.start_login(browser)
        lookalikes = [
            self.settings.redirect_uri + ".evil.example.test",
            self.settings.redirect_uri + "/",
            self.settings.redirect_uri.replace("localhost", "localhost.evil.example.test"),
        ]
        results = []
        for lookalike in lookalikes:
            hop = self.user.authorize(_replace_query_value(location, "redirect_uri", lookalike))
            results.append((lookalike.removeprefix("http://"), hop.status, hop.location is None))
        ok = all(status == 400 and refused for _, status, refused in results)
        return _step(
            "a lookalike redirect URI is refused by the provider itself",
            ok,
            "; ".join(f"{uri} -> {status}, no redirect" for uri, status, _ in results),
        )
```

`lookalike_redirect_uri`: three redirect addresses that are not exactly the registered one (a suffix added, a trailing slash, a look-alike host) are sent to the provider, which must answer 400 itself without redirecting.

```python
    def code_reuse(self) -> Step:
        """An authorization code can be exchanged once; the second exchange is refused by the provider."""
        verifier = self.container.flow._tokens.token(64)
        code = self.authorize_code(
            client_id=self.settings.client_id, redirect_uri=self.settings.redirect_uri, verifier=verifier
        )
        provider = self.container.provider
        provider.exchange_code(code=code, code_verifier=verifier)
        try:
            provider.exchange_code(code=code, code_verifier=verifier)
        except ProviderError as error:
            return _step(
                "a code cannot be exchanged a second time",
                error.code == "invalid_grant",
                f"second exchange: {error.code} ({error.description})",
            )
        return _step("a code cannot be exchanged a second time", False, "the second exchange was accepted")
```

`code_reuse`: a code is obtained for the real client and exchanged once; the second exchange must fail with `invalid_grant`.

```python
    def wrong_pkce_verifier(self) -> Step:
        """Without the right PKCE verifier a stolen code is useless."""
        verifier = self.container.flow._tokens.token(64)
        code = self.authorize_code(
            client_id=self.settings.client_id, redirect_uri=self.settings.redirect_uri, verifier=verifier
        )
        try:
            self.container.provider.exchange_code(code=code, code_verifier="w" * 64)
        except ProviderError as error:
            return _step(
                "a stolen code is useless without the PKCE verifier",
                error.code == "invalid_grant",
                f"exchange with another verifier: {error.code} ({error.description})",
            )
        return _step("a stolen code is useless without the PKCE verifier", False, "the exchange was accepted")
```

`wrong_pkce_verifier`: a code obtained with one verifier is exchanged with another (64 letters `w`); the provider must refuse with `invalid_grant`.

```python
    def session_facts(self, browser: AppBrowser) -> Step:
        """The session answers with an identity and no tokens, and the server can use its access token."""
        me = browser.get("/me").get_json()
        profile = browser.get("/api/profile")
        ok = (
            me is not None
            and set(me) == {"subject", "username", "scopes", "session_expires_at"}
            and profile.status_code == 200
        )
        return _step(
            "the session shows who signed in, never a token, and the server calls the provider for the browser",
            ok,
            f"/me -> {sorted(me or {})}; /api/profile -> {profile.status_code} {profile.get_json()}",
        )
```

`session_facts`: `/me` must return exactly the four keys subject, username, scopes and session_expires_at (no token), and `/api/profile` must answer 200 (the server uses its access token on the browser's behalf).

```python
    def refresh_rotation(self, browser: AppBrowser) -> Step:
        """A refresh issues a new refresh token and the provider refuses the old one."""
        before = self.server_session()
        old = before.tokens.refresh_token or ""
        response = browser.post("/refresh", headers={"X-CSRF-Token": before.csrf_token})
        after = self.server_session()
        new = after.tokens.refresh_token or ""
        try:
            self.container.provider.refresh(old)
            reuse = "ACCEPTED"
        except ProviderError as error:
            reuse = error.code
        ok = response.status_code == 200 and new != old and reuse == "invalid_grant"
        return _step(
            "a refresh rotates the refresh token and the old one is refused",
            ok,
            f"POST /refresh -> {response.status_code}; refresh token changed: {new != old}; "
            f"old token at the provider: {reuse}",
        )
```

`refresh_rotation`: the refresh token is noted, `POST /refresh` is called with the CSRF token, the new token must differ, and presenting the old one to the provider must fail with `invalid_grant`.

```python
    def logout(self, browser: AppBrowser) -> Step:
        """Sign-out ends the session here and revokes the refresh token at the provider."""
        session = self.server_session()
        refresh_token = session.tokens.refresh_token or ""
        old_cookie = browser.cookie(SESSION_COOKIE)
        response = browser.post("/logout", data={"csrf_token": session.csrf_token})
        replay = self.new_browser()
        replay.client.set_cookie(SESSION_COOKIE, old_cookie or "", domain="localhost")
        after = replay.get("/me").status_code
        try:
            self.container.provider.refresh(refresh_token)
            revoked = "ACCEPTED"
        except LoginError as error:
            revoked = error.code if isinstance(error, ProviderError) else type(error).__name__
        ok = (
            response.status_code == 303
            and after == 401
            and revoked == "invalid_grant"
            and self.container.sessions.count() == 0
        )
        return _step(
            "after sign-out the old session and the old refresh token are both refused",
            ok,
            f"POST /logout -> {response.status_code}; old cookie -> {after}; refresh token at the provider: {revoked}",
        )
```

`logout`: the cookie is noted, `POST /logout` is called, a new browser with the old cookie must get 401, presenting the old refresh token must fail with `invalid_grant` (it was revoked) and the store must hold no session.

```python
    def scope_check(self) -> Step:
        """A route that needs an elevated scope refuses a sign-in that did not ask for it."""
        plain = self.new_browser()
        _, location = self.start_login(plain)
        _, back = self.authenticate(location)
        plain.follow_callback(back)
        denied = plain.get("/reports").status_code
        plain.post("/logout", data={"csrf_token": self.server_session().csrf_token})
        elevated = self.new_browser()
        _, location = self.start_login(elevated, scope="reports:read")
        _, back = self.authenticate(location)
        elevated.follow_callback(back)
        allowed = elevated.get("/reports").status_code
        elevated.post("/logout", data={"csrf_token": self.server_session().csrf_token})
        return _step(
            "a route that needs the reports:read scope refuses a sign-in without it",
            (denied, allowed) == (403, 200),
            f"/reports without the scope -> {denied}, with it -> {allowed}",
        )
```

`scope_check`: a login without the extra scope gets 403 from `/reports`; a login that asked for `reports:read` gets 200. Both sign out afterwards.

```python
    def public_client_needs_pkce(self) -> Step:
        """The public client has no secret, so the provider refuses its code exchange without a verifier."""
        verifier = self.container.flow._tokens.token(64)
        code = self.authorize_code(client_id=SPA_CLIENT_ID, redirect_uri=SPA_REDIRECT_URI, verifier=verifier)
        endpoint = self.container.provider.metadata().token_endpoint
        data = {
            "grant_type": "authorization_code",
            "client_id": SPA_CLIENT_ID,
            "code": code,
            "redirect_uri": SPA_REDIRECT_URI,
        }
        without = httpx.post(endpoint, data=data, timeout=30)
        code2 = self.authorize_code(client_id=SPA_CLIENT_ID, redirect_uri=SPA_REDIRECT_URI, verifier=verifier)
        with_verifier = httpx.post(endpoint, data={**data, "code": code2, "code_verifier": verifier}, timeout=30)
        ok = without.status_code == 400 and with_verifier.status_code == 200
        reason = without.json().get("error_description", without.json().get("error", ""))
        return _step(
            "a public client (no secret) cannot exchange a code without the PKCE verifier",
            ok,
            f"without a verifier -> {without.status_code} ({reason}); with it -> {with_verifier.status_code}",
        )
```

`public_client_needs_pkce`: the public client `notes-spa` has no secret. Exchanging its code without a verifier must give 400; with the verifier (using a second code) it must give 200.

```python
def _replace_query_value(url: str, name: str, value: str) -> str:
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    query[name] = value
    return parts._replace(query=urlencode(query)).geturl()
```

`_replace_query_value` returns an address with one query value replaced.

```python
def run_scenario(env: Mapping[str, str]) -> list[Step]:
    """Run every step in order against the provider named by ``env`` and return the results."""
    scenario = Scenario(env)
    steps: list[Step] = []
    try:
        steps.append(scenario.discovery())
        browser = scenario.new_browser()
        started, location = scenario.start_login(browser)
        steps.append(started)
        authenticated, back = scenario.authenticate(location)
        steps.append(authenticated)
        steps.append(scenario.complete_login(browser, back))
        steps.append(scenario.id_token_validation())
        steps.append(scenario.session_facts(browser))
        steps.append(scenario.refresh_rotation(browser))
        steps.append(scenario.logout(browser))
        steps.extend(
            [
                scenario.mismatched_state(),
                scenario.login_csrf(),
                scenario.replayed_callback(),
                scenario.lookalike_redirect_uri(),
                scenario.code_reuse(),
                scenario.wrong_pkce_verifier(),
                scenario.scope_check(),
                scenario.public_client_needs_pkce(),
            ]
        )
    finally:
        scenario.close()
    return steps
```

`run_scenario` runs all steps in order: discovery, start, authenticate, complete, ID token validation, session facts, refresh, logout, then the eight attack and stretch steps. A `finally` block always closes the clients.

```python
def main(argv: list[str] | None = None, *, out: Callable[[str], None] = print) -> int:
    """Run the scenario and print one line per step; exit 1 when a step fails."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    steps = run_scenario(os.environ)
    for number, step in enumerate(steps, start=1):
        out(f"{number:>2}. {'PASS' if step.passed else 'FAIL'}  {step.name}\n        {step.detail}")
    failed = [step for step in steps if not step.passed]
    out(f"{len(steps) - len(failed)} of {len(steps)} checks passed")
    return 1 if failed else 0
```

`main` takes optional arguments and an output function, runs the scenario from the environment and prints one numbered PASS or FAIL line with its detail per step, then the count.

```python
if __name__ == "__main__":
    sys.exit(main())
```

It returns 1 if any step failed, and when run as a program the value becomes the exit code.

### Line by line: `src/oidc_login/interfaces/scripted_browser.py`

```python
"""A scripted browser for the demo and the tests: it plays the user at the provider's login page and at the app.

It is deliberately small. The provider's login page is a form; this fills it in and reports where the provider
redirects. Nothing here is reachable from the running app.
"""
```

The docstring: a scripted browser for the demo and the tests. It plays the user at the provider's login page and at the app. It is small on purpose: the provider's login page is a form, this fills it in and reports where the provider redirects. Nothing here is reachable from the running app.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
```

Imports: `dataclass`, `HTMLParser` (the standard module that reads HTML and calls a method for each tag), `Any` and `urlsplit`.

```python
import httpx
from flask import Flask
from werkzeug.test import TestResponse
```

`httpx` (HTTP client), `Flask` (type) and Werkzeug's `TestResponse`.

```python
@dataclass(frozen=True, slots=True)
class Hop:
    """One response from the provider: its status, the ``Location`` it redirects to (if any) and the body."""

    status: int
    location: str | None
    body: str
```

`Hop` is one response from the provider: its status number, the `Location` header it redirects to (if any) and the body text.

```python
class _LoginForm(HTMLParser):
    """Finds the sign-in form in the provider's page: its action URL and its hidden fields."""

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._inside = False
```

`_LoginForm` is a small HTML parser. It looks for the sign-in form of the provider's page. It keeps the form's `action` address (where to post) and the form's hidden fields; `_inside` records whether the parser is between the form's start and end tags.

```python
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and (
            values.get("id") == "kc-form-login" or "login-actions/authenticate" in (values.get("action") or "")
        ):
            self.action, self._inside = values.get("action"), True
        elif tag == "input" and self._inside and values.get("type") == "hidden" and values.get("name"):
            self.fields[str(values["name"])] = values.get("value") or ""
```

`handle_starttag` is called for each start tag with its attributes (turned into a dictionary). A `form` tag counts as the sign-in form if its id is `kc-form-login` or its action contains `login-actions/authenticate` (Keycloak's address pattern); then `action` and `_inside` are set. An `input` of type `hidden` with a name, inside the form, is stored with its value (Keycloak puts one-time values in hidden fields that must be posted back).

```python
    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._inside = False
```

`handle_endtag` marks the end of the form.

```python
class ProviderBrowser:
    """The user's browser at the identity provider: keeps the provider's cookies, fills in the login form.

    Cookies are kept by hand: the provider marks some of them ``Secure`` even on ``http://localhost``, which a real
    browser accepts (localhost counts as secure) but a plain HTTP client's cookie jar rightly drops.
    """
```

`ProviderBrowser` is the user's browser at the identity provider. It keeps the provider's cookies by hand: the docstring explains the provider marks some cookies `Secure` even on `http://localhost`, which a real browser accepts (localhost counts as secure) but a plain HTTP client's cookie jar rightly drops.

```python
    def __init__(self, username: str, password: str, timeout_seconds: float = 300) -> None:
        self._username = username
        self._password = password
        self._http = httpx.Client(follow_redirects=False, timeout=timeout_seconds)
        self._cookies: dict[str, str] = {}
```

The constructor stores the username and password, creates an HTTP client that does not follow redirects (the scripted user needs to see each redirect) with a generous timeout, and an empty cookie dictionary.

```python
    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()
```

`close` closes the client.

```python
    def _send(self, method: str, url: str, data: dict[str, str] | None = None) -> httpx.Response:
        headers = (
            {"Cookie": "; ".join(f"{name}={value}" for name, value in self._cookies.items())} if self._cookies else {}
        )
```

`_send` builds a `Cookie` header from the stored cookies (or none).

```python
        response = self._http.request(method, url, data=data, headers=headers)
```

It sends the request.

```python
        for header in response.headers.get_list("set-cookie"):
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            if "Max-Age=0" in header or value in {"", '""'}:
                self._cookies.pop(name, None)
            else:
                self._cookies[name] = value
```

For each `Set-Cookie` header it splits the name from the rest, takes the value before the first `;`, and removes the cookie if the header says `Max-Age=0` or the value is empty, else stores it.

```python
        return response
```

The response is returned.

```python
    def authorize(self, authorization_url: str) -> Hop:
        """Open the authorization URL. At the login page, sign in; return the provider's final answer for this
        request (normally a redirect back to the app, or an error page)."""
        first = self._send("GET", authorization_url)
        if first.status_code in {301, 302, 303}:
            return Hop(first.status_code, first.headers.get("location"), first.text)
```

`authorize` opens the authorization address. A redirect straight away (the provider already has a session for this browser) is returned as a `Hop`.

```python
        form = _LoginForm()
        form.feed(first.text)
        if first.status_code != 200 or not form.action:
            return Hop(first.status_code, None, first.text)
```

Otherwise the page is parsed for the sign-in form. A non-200 answer or a page with no form (for example an error page for a bad redirect address) is returned with no location.

```python
        data = {**form.fields, "username": self._username, "password": self._password}
        second = self._send("POST", form.action, data)
        return Hop(second.status_code, second.headers.get("location"), second.text)
```

The form's hidden fields plus the username and password are posted to the form's action; the answer, normally a redirect back to the app carrying the code, is returned. The password goes only to the provider, never to the app.

```python
class AppBrowser:
    """The user's browser at the app, over the Flask test client, on https://localhost so the Secure cookie travels."""
```

`AppBrowser` is the user's browser at the app, over Flask's test client, on `https://localhost` so the Secure cookie travels.

```python
    def __init__(self, app: Flask) -> None:
        self.client = app.test_client()
```

The constructor creates the test client.

```python
    def request(self, method: str, path: str, **kwargs: Any) -> TestResponse:
        """Send a request to the app."""
        kwargs.setdefault("base_url", "https://localhost")
        return self.client.open(path, method=method, **kwargs)
```

`request` sends a request, with `https://localhost` as the base address unless the caller says otherwise.

```python
    def get(self, path: str, **kwargs: Any) -> TestResponse:
        """GET a path."""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> TestResponse:
        """POST to a path."""
        return self.request("POST", path, **kwargs)
```

Shortcuts `get` and `post`.

```python
    def cookie(self, name: str) -> str | None:
        """The value of one of the app's cookies, if the browser holds it."""
        found = self.client.get_cookie(name, domain="localhost")
        return None if found is None else found.value
```

`cookie` returns the value of one of the app's cookies, or `None`.

```python
    def follow_callback(self, location: str) -> TestResponse:
        """Do what the browser does after the provider redirects: GET the callback path and query on the app."""
        target = urlsplit(location)
        return self.get(f"{target.path}?{target.query}")
```

`follow_callback` does what the browser does after the provider redirects: it takes the path and query of the redirect address and requests them on the app.

```python
    def sign_in(self, provider: ProviderBrowser, scope: str | None = None) -> TestResponse:
        """A complete sign-in: start at the app, authenticate at the provider, come back to the callback."""
        start = self.get("/login" + (f"?scope={scope}" if scope else ""))
        hop = provider.authorize(start.headers["Location"])
        if hop.location is None:
            raise AssertionError(f"the provider did not redirect back (status {hop.status})")
        return self.follow_callback(hop.location)
```

`sign_in` does a complete sign-in: start at the app's `/login`, let the provider browser authenticate at the address in the `Location` header, raise an error if the provider did not redirect back, and follow the callback.

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
