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
