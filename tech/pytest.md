# pytest 9 and coverage

## What it is

**pytest** is a Python tool that finds and runs tests. A **test** is a function whose name starts with `test_`; it runs some code and uses `assert` to say what must be true. If an assert is false (or the code raises), the test **fails**; otherwise it **passes**. pytest prints which ones did what. Pinned: `pytest==9.1.1`, `pytest-cov==7.1.0` (which uses `coverage`). **Coverage** measures which lines of your code ran during the tests.

## Why this repository uses it

The lesson's claim is that each OAuth protection is real: a wrong `state`, a replayed callback, a forged token and a reused code are each *refused*, and a test says so. That takes three kinds of test: fast ones that check the rules with fakes, ones that talk to the real identity provider, and one that starts the real server process. pytest's **fixtures** (reusable set-up code) and **markers** (labels on tests) make that practical.

## Where it appears

| Path | What it does |
| --- | --- |
| `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.coverage.*]`) | Test folder, options, marker names, coverage settings. |
| `tests/unit/` (151 tests) | Domain rules, the login flow with fakes, the verifier, the provider adapter over a mock transport, the Flask app over fakes, settings, logging, stores. No provider needed. |
| `tests/integration/` (22 tests) | The adapter, token validation, the flow protections, sessions and refresh, stretch goals, against Keycloak. Marker `integration`. |
| `tests/e2e/` (5 tests) | A real gunicorn process, a scripted browser and Keycloak. Marker `e2e`. |
| `tests/fakes.py`, `tests/conftest.py` | Stand-ins for the ports and the one shared fixture. |
| `Makefile` | `test`, `test-integration`, `test-e2e`, `test-all`. |

## How it works underneath

1. `pytest tests/unit` walks the folder, imports every `test_*.py`, collects functions named `test_*`.
2. For each test it reads the **parameter names**. A parameter named like a fixture (`world`, `scenario`, `signer`) is filled by running that fixture first. Fixtures are found in the test file or in `conftest.py` files up the folder tree.
3. A fixture with `yield` runs set-up before the `yield`, hands the value to the test, and runs clean-up after, even if the test failed.
4. `assert` is rewritten at import time so a failure shows both sides of the comparison.
5. `@pytest.mark.parametrize` runs one test body with several inputs (each becomes its own test).
6. `-m integration` runs only tests carrying that marker; `-k text` selects by name.
7. With coverage, a tracer records every line (and every branch) executed.

### Ideas you need first

- **A test.** A small function that runs part of the program and states what must be true afterwards. If the statement is false, the test fails and shows why.
- **An assertion.** `assert x == 3` raises an error when `x` is not 3. pytest turns that into a readable failure message showing both values.
- **A unit test, an integration test and an end-to-end test.** A **unit** test checks one small piece with everything around it replaced by simple stand-ins. An **integration** test checks the piece together with a real neighbor (here a real database). An **end-to-end** test runs the whole program as a user would reach it (here a real server process over real HTTP).
- **A fake (a stand-in).** A simple object with the same methods as the real thing, used so a test needs no database or network: `FakeProvider` answers as an identity provider would, from a script, `FakeClock` returns a time the test moves by hand.
- **A fixture.** Set-up code a test asks for by naming it as a parameter. pytest runs it first and passes in what it returns. Code after a `yield` in a fixture is clean-up.
- **A marker.** A label on tests (`@pytest.mark.security`, or `pytestmark = pytest.mark.security` for a whole file) so you can run just those with `-m security`.
- **Coverage.** A measurement of which lines of the program ran during the tests. A line that never ran has no test protecting it.

## Walkthrough of this repository's use

### Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: needs the identity provider from docker-compose.yml (make up)",
    "e2e: the sign-in scenario over real HTTP against a started server and the provider (make up)",
]
```
`-ra` prints a summary of every non-passing outcome. `--strict-markers` makes an unknown marker (a typo) an error. A file declares `pytestmark = pytest.mark.integration` once to label all its tests.

### Fakes: the flow without a provider

`tests/fakes.py` contains `FakeClock` (time the test moves by hand), `CountingTokens` (predictable values), `Signer` (an RSA key that mints ID tokens and publishes a JWKS), `FakeVerifier` and `FakeProvider` (an `IdentityProvider` that records calls and returns scripted answers). The unit tests wire `LoginService` to these. That is how every rule of the flow, including all the ID-token failures, is tested in milliseconds, and why the domain and application layers are at 99 to 100% coverage.

```python
def test_the_none_algorithm_is_refused_before_any_key_is_looked_up(signer):
    unsigned = jwt.encode(claims(), key="", algorithm="none", headers={"kid": "key-1"})
    with pytest.raises(UnsupportedAlgorithmError, match="'none'"):
        verifier_for(signer).verify(unsigned)
```
Make a token with no signature, ask the verifier to accept it, and require the *named* error. `pytest.raises(Error, match="...")` passes only if that exception type is raised and its message matches the text.

```python
@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "....", "eyJhbGciOiJSUzI1NiJ9"])
def test_malformed_tokens_are_rejected_without_an_unexpected_error(signer, garbage):
```
Five inputs, five tests, one body.

### A mock network for the provider adapter

`tests/unit/test_oidc_provider.py` builds `httpx.Client(transport=httpx.MockTransport(handler))` (`tech/httpx.md`), so the adapter's retries, error mapping and exact request bodies are tested with no sockets.

### Integration tests: the real provider

```python
@pytest.fixture
def scenario() -> Iterator[Scenario]:
    env = dict(os.environ)
    env.setdefault("DEMO_USER_PASSWORD", "local-only-demo-user-password")
    instance = Scenario(env)
    yield instance
    instance.close()
```
`tests/conftest.py` has one fixture: a fresh `Scenario` (the demo's class, `tech/oauth2-and-openid-connect.md`) wired to the live Keycloak, with the HTTP clients closed afterwards. Each test calls one scenario method and asserts on the returned step:

```python
def test_a_callback_with_a_mismatched_state_is_refused(scenario: Scenario):
    step = scenario.mismatched_state()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0
```
`assert step.passed, step.detail` prints the step's explanation if it fails. The second assert checks the consequence: no session was created. The same method powers `make demo`, so the demo and the tests cannot disagree.

### End-to-end

`tests/e2e/test_server.py` picks a free port, starts `python -m gunicorn -c python:oidc_login.interfaces.gunicorn_conf "oidc_login.interfaces.wsgi:build_app()"` as a subprocess, waits up to 180 seconds for `/readyz`, signs in through a scripted browser, uses `/me`, refreshes, signs out, and finally sends SIGTERM and requires exit code 0 with the shutdown lines in the log. A parametrized test checks the app refuses to start with a missing client secret or `APP_ENV=production` over `http`.

### Coverage gate

```make
$(PY) -m pytest tests/unit --cov=oidc_login --cov-report=term
$(PY) -m coverage report --include='src/oidc_login/domain/*,src/oidc_login/application/*' --fail-under=95
```
```toml
[tool.coverage.run]
source = ["oidc_login"]
branch = true
```
`branch = true` counts both sides of each `if`. The second command fails the build below 95% for the domain and application folders. They stand at 99% (346 statements, 1 missed: a defensive line in `login_flow.py`). The whole package is lower (75% with unit tests alone) because the real HTTP adapters, `demo_cli.py`, `wsgi.py` and the scripted browser are exercised by the integration and end-to-end tests.

### Every test file

Collected counts: 151 unit tests (claims 21, http_app 27, jwks_verifier 15, logging_and_stores 5, login_flow 35, oidc_provider 17, pkce 11, scopes 4, settings 16), 22 integration tests (code_flow 4, flow_protections 6, provider_setup 3, session_lifecycle 5, stretch_goals 2, token_validation 2) and 5 end-to-end tests: 178 in all. A **parametrized** test (one function run with several inputs) counts once per input, which is why some counts exceed the number of functions listed.

**Helpers.** `tests/fakes.py`: `FakeClock` (time moved by hand), `CountingTokens`, `Signer` (generates an RSA key, mints ID tokens and publishes a key set), `id_token_claims(...)`, `access_token_hash(...)`, `FakeVerifier`, `FakeProvider` (an identity provider that records calls and returns scripted answers). `tests/conftest.py` sets `APP_ENV=test` and provides the `scenario` fixture (a fresh `Scenario` wired to the real Keycloak, closed afterwards).

**Unit tests (no provider).**

| File | Claims tested |
| --- | --- |
| `test_claims.py` | A good token yields the identity; the username falls back to the subject; each failed check raises its own error with a specific reason (parametrized); several audiences are fine when `azp` is this client; a little clock skew is tolerated, a lot is not; expiry is judged at the time given, not the wall clock; the access-token hash is checked when present and optional when absent. |
| `test_http_app.py` | `/login` redirects to the provider and sets a short-lived attempt cookie; the callback creates an opaque session cookie and clears the attempt cookie; no token ever reaches the browser; every response carries the security headers; a callback without a valid attempt is a generic 400 and sets no session; a mismatched state, a callback from another browser, and a replayed callback are refused; a refused code is a 400 and a forged token a 401; a provider outage is a 502; `/me` shows identity and scopes but no tokens; routes that need a session answer 401 without one; `/api/profile` calls userinfo with the server-held access token; refresh needs the CSRF token and rotates; a revoked refresh token gives 401 and drops the session; logout needs the CSRF token, ends the session and revokes; logout without a session is harmless; `/reports` needs the elevated scope; the home page changes with the session and HTML-escapes the username; health and readiness; unknown routes and an oversized body use the JSON error shape; an unexpected error leaks nothing; the authorization URL matches the flow. |
| `test_jwks_verifier.py` | Verifies a token signed by the published key; rejects a different key with the same `kid`, a changed byte in the claims, `alg: none`, the HS256 algorithm-confusion attack, malformed tokens (five inputs), and a token without a `kid`; an unknown `kid` refetches once and picks up a rotated key; forged tokens cannot cause more than one refetch per interval; non-signing and malformed keys are ignored; expired claims are not the verifier's job. |
| `test_logging_and_stores.py` | Tokens, codes, secrets and cookies are redacted by field name; the formatter writes one redacted JSON line; a pending login can be taken once; expired attempts are dropped and the store is bounded; the session store replaces only sessions that still exist and purges the inactive. |
| `test_login_flow.py` | `start` sends only the challenge; a scope off the allow-list is not requested; a full sign-in keeps tokens on the server; a callback not tied to this browser is refused before any exchange; a mismatched state burns the attempt; a successful callback cannot be replayed; an attempt expires; no code is refused; a code cannot be exchanged twice; a wrong PKCE verifier is refused; a bad ID token is rejected with its own reason and makes no session; an unaccepted algorithm is rejected; a token response without an ID token is refused; sessions resolve until idle too long and end at the absolute lifetime; unknown cookies resolve to nothing; refresh rotates; a refused refresh drops the session; refreshing an ended session is refused; the access token refreshes only near expiry; sign-out revokes, ends locally even when revocation fails, and is harmless without a session; CSRF comparison; the session id is stored only as a hash; old sessions are purged; a granted extra scope is recorded. |
| `test_oidc_provider.py` | Discovery is fetched once and cached; a document for another issuer or missing an endpoint is refused; GETs retry with backoff and then succeed, give up with a clear error, and a client error is not retried; the authorization URL has the code flow, S256 and the one redirect URI; the code exchange is a POST with the verifier and secret in the body; the provider's error code is carried and the POST is not retried; a non-JSON error body still yields a provider error; a token response missing fields is invalid; a network failure on a POST is "provider unavailable"; refresh and revoke send the expected forms; a failed revocation raises; userinfo sends the bearer token and maps errors; the key set is fetched from the discovered address and the client can be closed. |
| `test_pkce.py` | The challenge matches the RFC 7636 appendix B example; it has no padding and is URL-safe; verifiers of 43 to 128 allowed characters are valid and others refused. |
| `test_scopes.py` | The base scope is always requested; an allow-listed extra is added once; others are dropped, not forwarded; `require` passes for a granted scope and names the missing one. |
| `test_settings.py` | Defaults and normalization; the client secret is never printed; required settings are required; the environment name must be known; a redirect URI must be absolute http(s) without query or fragment; plain http is for localhost only; production requires https everywhere and secure cookies; the issuer must be a URL and integers are checked; an empty extra-scope list allows none. |

**Integration tests (need `make up`).** `test_provider_setup.py`: the discovery document and signing keys are reachable; the provider publishes exactly one RS256 signing key; the app is registered as a confidential client with one exact redirect URI. `test_code_flow.py`: the authorization request carries state, nonce and an S256 challenge and no secret; the user authenticates at the provider and comes back to the registered address; a full sign-in works and the browser gets only an opaque cookie; the token exchange is one server-to-server POST with the verifier and the secret. `test_token_validation.py`: the real ID token is RS256-signed and carries the claims the app checks; a wrong audience, an expired token, a wrong key, `alg: none` and a wrong nonce are each rejected with a clear reason. `test_flow_protections.py`: mismatched state, login CSRF, replay, look-alike redirect addresses, code reuse and wrong PKCE verifier (the scenario methods, each with `assert step.passed, step.detail` and a check that no session was created). `test_session_lifecycle.py`: identity and no token with the server using the access token; refresh issues a new refresh token and the old is refused; the session survives a refresh; after sign-out both the session and the refresh token are refused; a provider-revoked refresh token ends the session on next use. `test_stretch_goals.py`: the `reports:read` route and the public client.

**End-to-end tests (need `make up`).** `test_server.py` picks a free port, starts the real gunicorn as a subprocess, waits up to 180 seconds for `/readyz`, and runs: the whole flow against it with a scripted browser; `SIGTERM` makes it exit 0 with the shutdown lines in its log; and the server refuses to start, exiting non-zero with a message on standard error, in three cases (parametrized): an empty `OIDC_CLIENT_SECRET` (`OIDC_CLIENT_SECRET is required`), `APP_ENV=production` with the `http` redirect address of the local setup (`https in production`), and an `http` redirect address on a host other than localhost (`only accepted for localhost`).

### Line by line: `tests/conftest.py`

A file named `conftest.py` is read by pytest automatically; fixtures defined here are available to every test under `tests/`. A **fixture** is a function marked `@pytest.fixture` whose return value is handed to any test that has a parameter with the same name.

```python
"""Fixtures for the tests that talk to the identity provider (make up). The unit tests need none of this."""
```

The docstring: fixtures for the tests that talk to the identity provider (`make up`). The unit tests need none of this.

```python
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
```

Type hints kept as text; imports of `os`, `Iterator` and `pytest`.

```python
from oidc_login.interfaces.demo_cli import Scenario
```

The `Scenario` class of the demo is reused by the integration tests.

```python
os.environ.setdefault("APP_ENV", "test")
```

`os.environ.setdefault("APP_ENV", "test")` sets the environment to `test` unless it is already set; it runs when this file loads, before any test.

```python
@pytest.fixture
def scenario() -> Iterator[Scenario]:
    """A fresh app (no sessions, no cached state) wired to the real provider, and scripted browsers."""
    env = dict(os.environ)
    env.setdefault("DEMO_USER_PASSWORD", "local-only-demo-user-password")
    instance = Scenario(env)
    yield instance
    instance.close()
```

The `scenario` fixture copies the environment, supplies a local-only demo password if none is set, builds a fresh `Scenario` (a fresh app with no sessions and no cached state, wired to the real provider, plus scripted browsers), hands it to the test with `yield` and closes it afterwards. The code after `yield` is the cleanup.

### Line by line: `tests/fakes.py`

```python
"""Stand-ins for the ports, faithful enough to exercise the flow without a provider: a signing key that mints ID
tokens, a provider that enforces PKCE, single-use codes and refresh-token rotation, and a hand-moved clock."""
```

The docstring: stand-ins for the ports, faithful enough to exercise the flow without a provider. A stand-in that mimics an interface is a **fake**. There are a signing key that mints ID tokens, a provider that enforces PKCE, single-use codes and refresh-token rotation, and a clock moved by hand.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import base64
import hashlib
import itertools
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
```

Imports: `base64`, `hashlib`, `itertools` (counters), `time`, `Callable`, date and time types and `Any`.

```python
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
```

PyJWT, an RSA key generator from `cryptography` and PyJWT's `RSAAlgorithm` (turns a public key into a JWK, the JSON form of a key).

```python
from oidc_login.domain.errors import ProviderError, ProviderUnavailableError
from oidc_login.domain.models import ProviderMetadata, TokenResponse
```

The two provider errors and the records.

```python
ISSUER = "http://localhost:8080/realms/demo"
CLIENT_ID = "notes-app"
REDIRECT_URI = "http://localhost:3000/callback"
START = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
```

Constants: a fake issuer address, the client id `notes-app`, the redirect address and a fixed `START` time (27 October 2026, 09:00 UTC).

```python
class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime = START) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)
```

`FakeClock` is a clock the test moves by hand: `now()` returns the stored time; `advance(minutes=5)` adds a `timedelta` built from the keyword arguments.

```python
class CountingTokens:
    """Predictable random values: t1, t2, ... (64-byte requests give a valid 43+ character PKCE verifier)."""

    def __init__(self) -> None:
        self._count = itertools.count(1)

    def token(self, nbytes: int = 32) -> str:
        number = next(self._count)
        return f"t{number}-" + "x" * max(nbytes - len(str(number)) - 2, 40 if nbytes >= 64 else 8)
```

`CountingTokens` returns predictable values `t1-xxx...`, `t2-xxx...`. `itertools.count(1)` counts 1, 2, 3 for ever. The padding of `x` characters makes a 64-byte request long enough (at least 40 padding characters) to be a valid PKCE verifier of 43 or more characters.

```python
class Signer:
    """An RSA key pair, its JWKS, and a way to mint tokens signed with it."""

    def __init__(self, kid: str = "key-1") -> None:
        self.kid = kid
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
```

`Signer` generates an RSA key pair (2048 bits, public exponent 65537, the usual choice) with a key id (`kid`).

```python
    def jwks(self) -> dict[str, Any]:
        public = RSAAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}
```

`jwks` returns the key set a provider would publish: the public key as a JWK plus the `kid`, `use: sig` and `alg: RS256`.

```python
    def mint(self, claims: dict[str, Any], *, algorithm: str = "RS256", headers: dict[str, Any] | None = None) -> str:
        return jwt.encode(claims, self.private_key, algorithm=algorithm, headers={"kid": self.kid, **(headers or {})})
```

`mint` signs a set of claims into a JWT with the private key, putting the `kid` in the header. Tests can pass another algorithm or extra header fields to build bad tokens.

```python
def id_token_claims(clock: FakeClock, *, nonce: str, subject: str = "user-1", **overrides: Any) -> dict[str, Any]:
    """Claims a well-behaved provider puts in an ID token for this app."""
    now = int(clock.now().timestamp())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": subject,
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
        "preferred_username": "demo-user",
        "email": "demo-user@example.test",
    }
    claims.update(overrides)
    return claims
```

`id_token_claims` builds the claims a well-behaved provider puts in an ID token for this app: issuer, audience, subject, expiry five minutes ahead, issued-at, the nonce, a username and an email. Keyword `overrides` replace any claim, so a test can make exactly one thing wrong.

```python
def access_token_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode()).digest()
    return base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode()
```

`access_token_hash` computes `at_hash` the way OpenID Connect defines it: the left half (16 bytes) of the SHA-256 of the access token, base64url encoded without padding.

```python
class FakeVerifier:
    """Verifier port backed by the same Signer, using the real verification class."""

    def __init__(self, signer: Signer) -> None:
        from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier

        self._inner = JwksTokenVerifier(signer.jwks, monotonic=time.monotonic)

    def verify(self, id_token: str) -> dict[str, Any]:
        return self._inner.verify(id_token)
```

`FakeVerifier` is a token verifier that uses the real verification class on the same signer's keys, so tests exercise the real signature code. The import is inside the constructor to avoid a circular import at load time.

```python
class FakeProvider:
    """An in-memory identity provider that behaves like the real one where it matters to the flow."""
```

`FakeProvider` is an in-memory identity provider that behaves like the real one where it matters to the flow.

```python
    def __init__(self, signer: Signer, clock: FakeClock) -> None:
        self.signer = signer
        self.clock = clock
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.codes: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, bool] = {}  # token -> still valid
        self._counter = itertools.count(1)
        self.last_authorization: dict[str, str] = {}
        self.id_token_overrides: dict[str, Any] = {}
        self.id_token_signer: Signer | None = None
        self.id_token_factory: Callable[[str, str], str] | None = None  # (nonce, access token) -> raw token
        self.omit_id_token = False
        self.unavailable = False
        self.access_lifetime = 120
        self.granted_scope = "openid profile email"
```

Its state: the signer and clock; a list of requests it received (tests assert on it); one-time codes; refresh tokens with a "still valid" flag; and switches a test can set: extra claims, another signer, a factory for custom tokens, omit the ID token, simulate being unavailable, the access lifetime (120 s) and the granted scope.

```python
    def metadata(self) -> ProviderMetadata:
        if self.unavailable:
            raise ProviderUnavailableError("down")
        return ProviderMetadata(
            ISSUER, f"{ISSUER}/auth", f"{ISSUER}/token", f"{ISSUER}/certs", f"{ISSUER}/userinfo", f"{ISSUER}/revoke"
        )
```

`metadata` raises `ProviderUnavailableError` when set to be down, else returns the six addresses.

```python
    def authorization_url(self, *, state: str, nonce: str, code_challenge: str, scope: str) -> str:
        self.last_authorization = {"state": state, "nonce": nonce, "code_challenge": code_challenge, "scope": scope}
        return f"{ISSUER}/auth?state={state}&nonce={nonce}&code_challenge={code_challenge}&scope={scope}"
```

`authorization_url` records the state, nonce, challenge and scope, and returns a made-up address carrying them.

```python
    def issue_code(self) -> str:
        """What the provider does after the user signs in: a one-time code bound to the challenge and nonce."""
        code = f"code-{next(self._counter)}"
        self.codes[code] = dict(self.last_authorization)
        return code
```

`issue_code` plays what the provider does after the user signs in: a one-time code bound to the recorded challenge and nonce.

```python
    def exchange_code(self, *, code: str, code_verifier: str) -> TokenResponse:
        self.requests.append(("exchange", {"code": code, "code_verifier": code_verifier}))
        grant = self.codes.pop(code, None)  # single use
        if grant is None:
            raise ProviderError("invalid_grant", "Code not valid")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        if challenge != grant["code_challenge"]:
            raise ProviderError("invalid_grant", "PKCE verification failed")
        return self._tokens(grant["nonce"], grant["scope"], with_id_token=True)
```

`exchange_code` records the request. `pop` removes the code, so a second use finds nothing and raises `invalid_grant`. It computes the S256 challenge of the verifier and compares it with the stored one; a mismatch raises `invalid_grant` "PKCE verification failed". Otherwise tokens with an ID token are issued.

```python
    def refresh(self, refresh_token: str) -> TokenResponse:
        self.requests.append(("refresh", {"refresh_token": refresh_token}))
        if not self.refresh_tokens.get(refresh_token):
            raise ProviderError("invalid_grant", "Token is not active")
        self.refresh_tokens[refresh_token] = False  # rotation: the old one stops working
        return self._tokens("", self.granted_scope, with_id_token=False)
```

`refresh` accepts a refresh token only if it is still valid, then marks it used (rotation) and issues new tokens without an ID token.

```python
    def revoke(self, refresh_token: str) -> None:
        self.requests.append(("revoke", {"refresh_token": refresh_token}))
        self.refresh_tokens[refresh_token] = False
```

`revoke` marks the token invalid.

```python
    def userinfo(self, access_token: str) -> dict[str, Any]:
        self.requests.append(("userinfo", {"access_token": access_token}))
        return {"sub": "user-1", "preferred_username": "demo-user", "email": "demo-user@example.test"}
```

`userinfo` returns a fixed user.

```python
    def _tokens(self, nonce: str, scope: str, *, with_id_token: bool) -> TokenResponse:
        number = next(self._counter)
        access, refresh = f"access-{number}", f"refresh-{number}"
        self.refresh_tokens[refresh] = True
        id_token = None
        if with_id_token and self.id_token_factory is not None:
            id_token = self.id_token_factory(nonce, access)
        elif with_id_token and not self.omit_id_token:
            claims = id_token_claims(self.clock, nonce=nonce, at_hash=access_token_hash(access))
            claims.update(self.id_token_overrides)
            id_token = (self.id_token_signer or self.signer).mint({k: v for k, v in claims.items() if v is not None})
        return TokenResponse(access, refresh, id_token, self.access_lifetime, scope)
```

`_tokens` makes numbered access and refresh tokens and remembers the refresh token as valid. The ID token comes from the custom factory if set; otherwise, unless omitted, it is built from standard claims with `at_hash`, with overrides applied and `None` values removed (so a test can delete a claim), and signed by the chosen signer. The `TokenResponse` is returned.

### Line by line: `tests/unit/test_pkce.py`

```python
import pytest

from oidc_login.domain.pkce import challenge_for, is_valid_verifier
```

Imports of `pytest` and the two PKCE functions.

```python
def test_the_challenge_matches_the_rfc_7636_appendix_b_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
```

The challenge for the verifier `dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk` must be `E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM`: this is the worked example in Appendix B of RFC 7636, so the code is checked against the standard itself.

```python
def test_the_challenge_has_no_padding_and_is_url_safe():
    challenge = challenge_for("a" * 64)
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge
    assert len(challenge) == 43
```

A challenge has no `=` padding, no `+` and no `/` (it is URL-safe) and is exactly 43 characters (32 bytes in base64url).

```python
@pytest.mark.parametrize("verifier", ["a" * 43, "a" * 128, "A-._~" + "b" * 40])
def test_verifiers_of_43_to_128_unreserved_characters_are_valid(verifier):
    assert is_valid_verifier(verifier)
```

`parametrize` runs one test per valid verifier: 43 characters, 128 characters and a mix with the allowed symbols `-`, `.`, `_`, `~`.

```python
@pytest.mark.parametrize("verifier", ["", "short", "a" * 42, "a" * 129, "has space" + "a" * 40, "plus+" + "a" * 40])
def test_other_verifiers_are_refused(verifier):
    assert not is_valid_verifier(verifier)
    with pytest.raises(ValueError, match="43 to 128"):
        challenge_for(verifier)
```

Six invalid verifiers: empty, short, 42 characters, 129 characters, one with a space and one with a plus sign. Each is refused by `is_valid_verifier`, and `challenge_for` raises `ValueError` with "43 to 128" in the message.

### Line by line: `tests/unit/test_scopes.py`

```python
import pytest

from oidc_login.domain.errors import InsufficientScopeError
from oidc_login.domain.scopes import requested_scope, require
```

Imports.

```python
ALLOWED = frozenset({"reports:read"})
```

`ALLOWED` is a frozen set with only `reports:read`.

```python
def test_the_base_scope_is_always_requested():
    assert requested_scope([], ALLOWED) == "openid profile email"
```

With no extra scopes, the request is exactly `openid profile email`.

```python
def test_an_allow_listed_extra_scope_is_added_once():
    assert requested_scope(["reports:read", "reports:read"], ALLOWED) == "openid profile email reports:read"
```

Asking twice for the same allowed scope adds it once (the set removes the duplicate).

```python
def test_scopes_that_are_not_on_the_allow_list_are_dropped_not_forwarded():
    assert requested_scope(["admin", "reports:read", "offline_access"], ALLOWED) == "openid profile email reports:read"
```

`admin` and `offline_access` are not on the allow-list and are dropped, not forwarded.

```python
def test_require_passes_for_a_granted_scope_and_names_the_missing_one():
    require(frozenset({"openid", "reports:read"}), "reports:read")
    with pytest.raises(InsufficientScopeError, match="reports:read") as error:
        require(frozenset({"openid"}), "reports:read")
    assert error.value.scope == "reports:read"
```

`require` passes when the scope is granted; when it is missing, it raises `InsufficientScopeError` whose message contains the scope and whose `scope` attribute is `reports:read`.

### Line by line: `tests/unit/test_claims.py`

```python
from datetime import timedelta

import pytest
```

Imports: `timedelta` and `pytest`.

```python
from oidc_login.domain.claims import Expectations, check_access_token_hash, check_id_token_claims
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
from tests.fakes import CLIENT_ID, ISSUER, START, FakeClock, access_token_hash, id_token_claims
```

Imports of the claim checks and all the validation errors.

```python
from tests.fakes import CLIENT_ID, ISSUER, START, FakeClock, access_token_hash, id_token_claims
```

Imports of the shared constants and helpers from the fakes.

```python
NONCE = "the-nonce-this-login-sent"
EXPECTED = Expectations(issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE, now=START)
```

`NONCE` is the nonce this test's login "sent". `EXPECTED` is what the check expects: the fake issuer, the client id, that nonce and the fixed time `START` (the leeway is the default 30 seconds).

```python
def claims(**overrides):
    return id_token_claims(FakeClock(), nonce=NONCE, **overrides)
```

`claims(**overrides)` builds a good claim set for that nonce with any overrides applied.

```python
def test_a_good_token_yields_the_identity():
    identity = check_id_token_claims(claims(), EXPECTED)
    assert (identity.subject, identity.username, identity.email) == ("user-1", "demo-user", "demo-user@example.test")
```

A good token yields the identity: subject `user-1`, username `demo-user`, email.

```python
def test_the_username_falls_back_to_the_subject():
    identity = check_id_token_claims(claims(preferred_username=None, email=None), EXPECTED)
    assert (identity.username, identity.email) == ("user-1", None)
```

With no `preferred_username` and no email, the username falls back to the subject and the email is `None`. (In the fakes, an override of `None` removes the claim.)

```python
@pytest.mark.parametrize(
    ("overrides", "error", "reason"),
    [
        (
            {"iss": "http://evil.example.test/realms/demo"},
            IssuerMismatchError,
            "issuer claim does not match the provider",
        ),
        ({"iss": ISSUER + "/"}, IssuerMismatchError, "issuer"),
        ({"aud": "some-other-client"}, AudienceMismatchError, "audience claim does not match client id"),
        ({"aud": ["a", "b"]}, AudienceMismatchError, "audience"),
        ({"aud": [CLIENT_ID, "other"], "azp": "other"}, AuthorizedPartyMismatchError, "authorized party"),
        ({"exp": int(START.timestamp()) - 300}, TokenExpiredError, "token has expired"),
        ({"iat": int(START.timestamp()) + 3600}, TokenNotYetValidError, "not valid yet"),
        ({"nonce": "another-logins-nonce"}, NonceMismatchError, "nonce mismatch: possible token substitution"),
        ({"nonce": None}, NonceMismatchError, "nonce"),
        ({"sub": None}, MissingClaimError, "'sub'"),
        ({"sub": ""}, MissingClaimError, "'sub'"),
        ({"exp": None}, MissingClaimError, "'exp'"),
        ({"exp": "tomorrow"}, MissingClaimError, "'exp'"),
        ({"aud": None}, MissingClaimError, "'aud'"),
        ({"aud": 7}, MissingClaimError, "'aud'"),
    ],
)
```

`parametrize` with three values per case: the overrides, the error class and a text the message must contain. Fifteen cases, each breaks one thing: an issuer of another host; an issuer with a trailing `/` (exact comparison, no tolerance); another client as audience; an audience list without this client; two audiences with the wrong authorized party; an `exp` 300 seconds in the past; an `iat` an hour in the future; a different nonce; a missing nonce; a missing or empty `sub`; a missing or non-numeric `exp`; a missing or numeric `aud`.

```python
def test_each_failed_check_raises_its_own_error_with_a_specific_reason(overrides, error, reason):
    body = {key: value for key, value in claims().items() if overrides.get(key, ...) is not None}
    body.update({key: value for key, value in overrides.items() if value is not None})
    with pytest.raises(error, match=reason) as raised:
        check_id_token_claims(body, EXPECTED)
    assert isinstance(raised.value, TokenValidationError)
```

For each case the body is built so that overridden claims set to `None` are removed and others replaced. The check must raise the named error type with the message matching the text, and the error must be a `TokenValidationError`.

```python
def test_several_audiences_are_fine_when_the_authorized_party_is_this_client():
    identity = check_id_token_claims(claims(aud=[CLIENT_ID, "account"], azp=CLIENT_ID), EXPECTED)
    assert identity.subject == "user-1"
```

Several audiences are fine when the authorized party is this client.

```python
def test_a_little_clock_skew_is_tolerated_but_not_a_lot():
    skewed = claims(exp=int(START.timestamp()) - 10)
    assert check_id_token_claims(skewed, EXPECTED).subject == "user-1"  # 10 s late, 30 s leeway
    with pytest.raises(TokenExpiredError):
        check_id_token_claims(claims(exp=int(START.timestamp()) - 31), EXPECTED)
    future = claims(iat=int(START.timestamp()) + 29)
    assert check_id_token_claims(future, EXPECTED).subject == "user-1"
```

Clock skew: an `exp` 10 seconds in the past is accepted (the leeway is 30); 31 seconds in the past is refused; an `iat` 29 seconds in the future is accepted.

```python
def test_expiry_is_judged_at_the_time_given_not_the_wall_clock():
    later = Expectations(
        issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE, now=START + timedelta(days=1), leeway=timedelta(0)
    )
    with pytest.raises(TokenExpiredError):
        check_id_token_claims(claims(), later)
```

Expiry is judged at the time given to the check, not the wall clock: with `now` a day later and no leeway, the same token is expired.

```python
def test_the_access_token_hash_is_checked_when_present_and_optional_when_absent():
    check_access_token_hash({"at_hash": access_token_hash("the-access-token")}, "the-access-token")
    check_access_token_hash({}, "anything")
    with pytest.raises(TokenValidationError, match="access token hash"):
        check_access_token_hash({"at_hash": access_token_hash("one")}, "another")
    with pytest.raises(TokenValidationError, match="access token hash"):
        check_access_token_hash({"at_hash": 5}, "another")
```

`at_hash`: a correct hash passes; an absent one passes; a hash of another token fails with "access token hash"; a non-text `at_hash` fails too.

### Line by line: `tests/unit/test_settings.py`

```python
import pytest

from oidc_login.infrastructure.settings import ConfigError, Settings
```

Imports.

```python
BASE = {
    "OIDC_ISSUER": "http://localhost:8080/realms/demo/",
    "OIDC_CLIENT_ID": "notes-app",
    "OIDC_CLIENT_SECRET": "super-secret-value",
    "OIDC_REDIRECT_URI": "http://localhost:3000/callback",
    "APP_ENV": "development",
}
```

`BASE` is a minimal valid development environment: issuer (with a trailing slash), client id, a placeholder secret, redirect address and `APP_ENV=development`.

```python
def test_defaults_and_normalization():
    settings = Settings.from_environment(BASE)
    assert settings.issuer == "http://localhost:8080/realms/demo"  # no trailing slash
    assert settings.discovery_base == settings.issuer
    assert settings.port == 3000
    assert settings.cookie_secure is True
    assert settings.allowed_extra_scopes == frozenset({"reports:read"})
    assert (settings.session_idle_seconds, settings.session_absolute_seconds) == (900, 28800)
```

Defaults and normalization: the trailing slash is removed from the issuer; the discovery base equals the issuer; port 3000; Secure cookies on; the extra scopes are `reports:read`; idle 900 and absolute 28,800 seconds.

```python
def test_the_client_secret_is_never_printed():
    assert "super-secret-value" not in repr(Settings.from_environment(BASE))
```

The printed form of the settings does not contain the secret.

```python
@pytest.mark.parametrize("name", ["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"])
def test_required_settings_are_required(name):
    env = {key: value for key, value in BASE.items() if key != name}
    with pytest.raises(ConfigError, match=name):
        Settings.from_environment(env)
```

For each of four required settings, removing it raises `ConfigError` naming it.

```python
def test_the_environment_name_must_be_known():
    with pytest.raises(ConfigError, match="APP_ENV"):
        Settings.from_environment({**BASE, "APP_ENV": "staging"})
```

`APP_ENV=staging` is refused.

```python
@pytest.mark.parametrize(
    "uri",
    [
        "/callback",
        "ftp://localhost/callback",
        "http://localhost:3000/callback?x=1",
        "http://localhost:3000/callback#f",
        "http://",
    ],
)
def test_a_redirect_uri_must_be_an_absolute_http_url_without_query_or_fragment(uri):
    with pytest.raises(ConfigError, match="OIDC_REDIRECT_URI"):
        Settings.from_environment({**BASE, "OIDC_REDIRECT_URI": uri})
```

Five bad redirect addresses (no host, wrong scheme, with a query, with a fragment, no host after the scheme) are refused with a message naming `OIDC_REDIRECT_URI`.

```python
def test_plain_http_is_for_localhost_only():
    with pytest.raises(ConfigError, match="only accepted for localhost"):
        Settings.from_environment({**BASE, "OIDC_REDIRECT_URI": "http://app.example.test/callback"})
    assert Settings.from_environment(
        {**BASE, "OIDC_REDIRECT_URI": "https://app.example.test/callback"}
    ).redirect_uri.startswith("https")
```

Plain `http` is accepted only for localhost; an `https` address on another host is accepted.

```python
def test_production_requires_https_everywhere_and_secure_cookies():
    production = {**BASE, "APP_ENV": "production"}
    with pytest.raises(ConfigError, match="https in production"):
        Settings.from_environment(production)
    https = {
        **production,
        "OIDC_REDIRECT_URI": "https://app.example.test/callback",
        "OIDC_ISSUER": "https://id.example.test/realms/demo",
    }
    assert Settings.from_environment(https).app_env == "production"
    with pytest.raises(ConfigError, match="COOKIE_SECURE"):
        Settings.from_environment({**https, "COOKIE_SECURE": "false"})
    with pytest.raises(ConfigError, match="OIDC_ISSUER must use https"):
        Settings.from_environment({**https, "OIDC_ISSUER": "http://id.example.test/realms/demo"})
```

In production, the `http` addresses are refused ("https in production"); with `https` for both the redirect and the issuer, production is accepted; `COOKIE_SECURE=false` is then refused; and an `http` issuer is refused.

```python
def test_the_issuer_must_be_a_url_and_integers_are_checked():
    with pytest.raises(ConfigError, match="OIDC_ISSUER"):
        Settings.from_environment({**BASE, "OIDC_ISSUER": "localhost"})
    with pytest.raises(ConfigError, match="APP_PORT"):
        Settings.from_environment({**BASE, "APP_PORT": "abc"})
    with pytest.raises(ConfigError, match="APP_PORT"):
        Settings.from_environment({**BASE, "APP_PORT": "0"})
    with pytest.raises(ConfigError, match="SESSION_IDLE_SECONDS"):
        Settings.from_environment({**BASE, "SESSION_IDLE_SECONDS": "99999"})
```

An issuer that is not a URL, a non-numeric port, a port of 0, and an idle time of 99,999 seconds (more than the absolute lifetime) are all refused, each naming its setting.

```python
def test_an_empty_extra_scope_list_allows_none():
    assert Settings.from_environment({**BASE, "OIDC_ALLOWED_EXTRA_SCOPES": ""}).allowed_extra_scopes == frozenset()
```

An empty `OIDC_ALLOWED_EXTRA_SCOPES` allows no extra scopes.

### Line by line: `tests/unit/test_logging_and_stores.py`

```python
import io
import json
import logging
from datetime import timedelta
```

Imports: `io`, `json`, `logging` and `timedelta`.

```python
from oidc_login.domain.models import PendingLogin
from oidc_login.infrastructure.logging import REDACTED, JsonFormatter, configure_logging, redact
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
from tests.fakes import START, FakeClock
```

Imports of the pending-login record, the logging pieces, the two in-memory stores and the shared fakes.

```python
def test_tokens_codes_secrets_and_cookies_are_redacted_by_field_name():
    fields = {
        "access_token": "a",
        "refresh_token": "r",
        "id_token": "i",
        "code": "c",
        "code_verifier": "v",
        "client_secret": "s",
        "nonce": "n",
        "state": "st",
        "session_id": "x",
        "cookie": "c",
        "authorization": "Bearer x",
        "subject": "user-1",
        "event": "login.completed",
        "status": 200,
    }
    cleaned = redact(fields)
    assert {key for key, value in cleaned.items() if value == REDACTED} == set(fields) - {"subject", "event", "status"}
```

Fourteen fields are passed to `redact`. Eleven have sensitive names (the three tokens, `code`, `code_verifier`, `client_secret`, `nonce`, `state`, `session_id`, `cookie` and `authorization`) and three do not (`subject`, `event`, `status`). The redacted keys must be all except those three.

```python
def test_the_formatter_writes_one_redacted_json_line():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.oidc.json")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
```

A logger is wired to an in-memory stream with the JSON formatter; `propagate = False` stops records from going to the root logger as well.

```python
    logger.info("exchanged", extra={"subject": "user-1", "access_token": "eyJhbGciOi-secret"})
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")
```

It logs a line with a subject and an access token, then an exception.

```python
    first, second = (json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{"))
    assert first["subject"] == "user-1"
    assert first["access_token"] == REDACTED
    assert "eyJhbGciOi-secret" not in stream.getvalue()
    assert "ValueError: boom" in second["exception"]
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING
```

Both lines parse as JSON. The subject is kept, the access token is redacted and its text appears nowhere; the exception text is included; `configure_logging("WARNING")` sets the root level.

```python
def pending(attempt_id, created_at=START):
    return PendingLogin(attempt_id, "state", "nonce", "v" * 64, "openid", created_at)
```

`pending(attempt_id, created_at)` builds a pending login with fixed state, nonce, a 64-character verifier and scope.

```python
def test_a_pending_login_can_be_taken_once():
    store = InMemoryPendingLoginStore(FakeClock(), 600)
    store.put(pending("a"))
    assert store.pop("a") is not None
    assert store.pop("a") is None
    assert store.pop("never") is None
```

A pending login can be taken once: the first `pop` returns it, the second and an unknown id return `None`.

```python
def test_expired_attempts_are_dropped_when_a_new_one_arrives_and_the_store_is_bounded():
    clock = FakeClock()
    store = InMemoryPendingLoginStore(clock, 600, max_entries=3)
    store.put(pending("old", clock.now()))
    clock.advance(seconds=601)
    for name in ("a", "b", "c", "d"):
        store.put(pending(name, clock.now()))
    assert store.pop("old") is None
    assert store.pop("a") is None  # the oldest was evicted to keep the store at three
    assert store.pop("d") is not None
```

With a lifetime of 600 seconds and room for 3: an attempt is stored, the clock moves 601 seconds, four new ones arrive. The old one has expired and is gone; `a` was evicted to keep the store at three; `d` is there.

```python
def test_the_session_store_replaces_only_sessions_that_still_exist_and_purges_the_inactive():
    from dataclasses import replace

    from oidc_login.domain.models import Identity, TokenSet, UserSession
```

The session-store test imports `replace` and the models inside the function.

```python
    tokens = TokenSet("a", "r", "i", START + timedelta(minutes=2), "openid")
    session = UserSession("h1", Identity("u", "u"), tokens, "csrf", START, START, START + timedelta(hours=8))
```

A token set and a session are built (expiry in 8 hours).

```python
    store = InMemorySessionStore()
    store.add(session)
    store.replace(replace(session, csrf_token="new"))
    replaced = store.get("h1")
    assert replaced is not None
    assert replaced.csrf_token == "new"
```

Adding, then replacing with a changed CSRF token, shows the new value.

```python
    store.delete("h1")
    store.replace(session)  # a refresh that finishes after sign-out must not resurrect the session
    assert store.get("h1") is None
    assert store.count() == 0
```

After deleting, `replace` with the old session does not bring it back: a refresh that finishes after sign-out must not resurrect the session. The store is empty.

```python
    store.add(session)
    store.add(replace(session, session_id_hash="h2", last_seen_at=START + timedelta(minutes=30)))
    assert store.purge_inactive(START + timedelta(minutes=31), timedelta(minutes=15)) == 1
    assert store.count() == 1
```

Two sessions are added, the second last seen 30 minutes after the start. Purging at minute 31 with a 15-minute idle limit removes the first (idle 31 minutes) and keeps the second.

### Line by line: `tests/unit/test_jwks_verifier.py`

```python
import base64
import hashlib
import hmac
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
```

Imports: `base64`, `hashlib`, `hmac`, `json`, PyJWT, `pytest` and the `serialization` helpers of `cryptography`.

```python
from oidc_login.domain.errors import SignatureInvalidError, UnsupportedAlgorithmError
from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier
from tests.fakes import FakeClock, Signer, id_token_claims
```

Imports of the two errors, the verifier and the fake signer.

```python
@pytest.fixture
def signer():
    return Signer("key-1")
```

The `signer` fixture is a signer with the key id `key-1`.

```python
def claims():
    return id_token_claims(FakeClock(), nonce="n")
```

`claims()` gives good claims.

```python
def verifier_for(signer, **kwargs):
    return JwksTokenVerifier(signer.jwks, **kwargs)
```

`verifier_for(signer)` builds a verifier whose key source is the signer's key set.

```python
def test_a_token_signed_by_the_published_key_verifies_and_returns_its_claims(signer):
    assert verifier_for(signer).verify(signer.mint(claims()))["sub"] == "user-1"
```

A token signed by the published key verifies and gives its claims.

```python
def test_a_token_signed_by_a_different_key_with_the_same_kid_is_rejected_for_its_signature(signer):
    forger = Signer("key-1")
    with pytest.raises(SignatureInvalidError, match="signature verification failed"):
        verifier_for(signer).verify(forger.mint(claims()))
```

A second signer with the same `kid` but a different key forges a token; the signature check rejects it ("signature verification failed"). The key id alone proves nothing.

```python
def test_a_token_with_one_changed_byte_in_its_claims_is_rejected(signer):
    header, payload, signature = signer.mint(claims()).split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["sub"] = "admin"
    forged_payload = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    with pytest.raises(SignatureInvalidError):
        verifier_for(signer).verify(f"{header}.{forged_payload}.{signature}")
```

A token's payload is decoded, the subject changed to `admin`, and re-encoded with the original header and signature. The signature no longer matches, so it is rejected.

```python
def test_the_none_algorithm_is_refused_before_any_key_is_looked_up(signer):
    unsigned = jwt.encode(claims(), key="", algorithm="none", headers={"kid": "key-1"})
    with pytest.raises(UnsupportedAlgorithmError, match="'none'"):
        verifier_for(signer).verify(unsigned)
```

A token with algorithm `none` is refused with `UnsupportedAlgorithmError` before any key lookup.

```python
def test_algorithm_confusion_with_the_public_key_as_an_hmac_secret_is_refused(signer):
    # The classic attack: sign with HS256 using the (public) RSA key as the secret. PyJWT itself refuses to build such a
    # token, so it is assembled by hand.
    public_pem = signer.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    signing_input = f"{part({'alg': 'HS256', 'typ': 'JWT', 'kid': 'key-1'})}.{part(claims())}"
    mac = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    confused = f"{signing_input}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"
    with pytest.raises(UnsupportedAlgorithmError, match="HS256"):
        verifier_for(signer).verify(confused)
```

The algorithm-confusion attack. The comment explains: sign with HS256 using the public RSA key as the HMAC secret; PyJWT itself refuses to build such a token, so the test builds it by hand: it encodes header and payload as base64url, computes an HMAC-SHA256 over them with the public key's PEM bytes, and appends it. The verifier must refuse it by algorithm (HS256 is not on the allow-list).

```python
@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "....", "eyJhbGciOiJSUzI1NiJ9"])
def test_malformed_tokens_are_rejected_without_an_unexpected_error(signer, garbage):
    with pytest.raises(SignatureInvalidError):
        verifier_for(signer).verify(garbage)
```

Five garbage inputs (empty, plain text, three dot-separated letters, dots only, a header only) all raise `SignatureInvalidError` and nothing unexpected.

```python
def test_a_token_without_a_kid_is_rejected(signer):
    token = jwt.encode(claims(), signer.private_key, algorithm="RS256")
    with pytest.raises(SignatureInvalidError, match="kid"):
        verifier_for(signer).verify(token)
```

A token with no `kid` in its header is rejected, with a message mentioning `kid`.

```python
def test_an_unknown_kid_refetches_the_keys_once_and_picks_up_a_rotated_key():
    old, new = Signer("old"), Signer("new")
    published = {"current": old}
    verifier = JwksTokenVerifier(lambda: published["current"].jwks(), min_refresh_seconds=0)
    assert verifier.verify(old.mint(claims()))["sub"] == "user-1"
    published["current"] = new  # the provider rotates
    assert verifier.verify(new.mint(claims()))["sub"] == "user-1"
```

Key rotation: the verifier first sees key `old`; the provider then publishes `new`; a token signed with `new` triggers one re-fetch (the refresh interval is 0 here) and verifies.

```python
def test_forged_tokens_cannot_make_the_app_refetch_keys_more_than_once_per_interval(signer):
    fetches = []
    clock = {"now": 0.0}

    def fetch():
        fetches.append(clock["now"])
        return signer.jwks()

    verifier = JwksTokenVerifier(fetch, min_refresh_seconds=30, monotonic=lambda: clock["now"])
    stranger = Signer("unknown-kid")
    for second in (0, 1, 2, 3):  # a burst of forged tokens inside one interval
        clock["now"] = float(second)
        with pytest.raises(SignatureInvalidError, match="signing key not found"):
            verifier.verify(stranger.mint(claims()))
    assert fetches == [0.0]
    clock["now"] = 31.0  # the interval has passed: one more look is allowed
    with pytest.raises(SignatureInvalidError, match="signing key not found"):
        verifier.verify(stranger.mint(claims()))
    assert fetches == [0.0, 31.0]
```

Forged tokens cannot force repeated fetching. A fake clock and a counting fetch function are used. Four forged tokens with an unknown `kid` at seconds 0 to 3 all fail with "signing key not found", but the fetch happened once. At second 31 (past the 30-second interval) one more look is allowed, so the fetch list is `[0.0, 31.0]`.

```python
def test_keys_not_meant_for_signing_and_malformed_keys_are_ignored(signer):
    document = signer.jwks()
    document["keys"].insert(0, {"kty": "RSA", "kid": "enc-key", "use": "enc", "n": "AQAB", "e": "AQAB"})
    document["keys"].insert(0, {"kty": "RSA", "kid": "broken", "use": "sig", "alg": "RS256"})
    document["keys"].insert(
        0, {"kty": "RSA", "kid": "other-alg", "use": "sig", "alg": "PS256", "n": "AQAB", "e": "AQAB"}
    )
    document["keys"].insert(0, "not an object")
    verifier = JwksTokenVerifier(lambda: document)
    assert verifier.verify(signer.mint(claims()))["sub"] == "user-1"
    with pytest.raises(SignatureInvalidError, match="signing key not found"):
        verifier.verify(Signer("enc-key").mint(claims()))
```

A key set with four bad entries (an encryption key, a broken key with no modulus, a key declared for another algorithm, and a non-object) still verifies a good token, and a token whose `kid` names the encryption key is "signing key not found".

```python
def test_expired_claims_are_not_the_verifiers_business(signer):
    expired = id_token_claims(FakeClock(), nonce="n", exp=1)
    assert (
        verifier_for(signer).verify(signer.mint(expired))["exp"] == 1
    )  # the domain judges expiry, after the signature
```

An expired token still verifies at the signature level: judging expiry is the domain's job, after the signature.

### Line by line: `tests/unit/test_login_flow.py`

These tests drive the whole flow with fakes: a fake provider, a real signature verifier on a test key, the real in-memory stores and a hand-moved clock. No network and no Keycloak is involved.

```python
from datetime import timedelta

import jwt
import pytest
```

Imports: `timedelta`, PyJWT (to build an unsigned token) and `pytest`.

```python
from oidc_login.application.login_flow import LoginConfig, LoginService, hash_session_id
```

The service, its config and the session-id hash function.

```python
from oidc_login.domain.errors import (
    AudienceMismatchError,
    NonceMismatchError,
    ProviderError,
    SessionNotFoundError,
    SignatureInvalidError,
    StateMismatchError,
    TokenExpiredError,
    TokenValidationError,
    UnsupportedAlgorithmError,
)
```

The errors the tests expect.

```python
from oidc_login.domain.pkce import challenge_for
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
```

The PKCE helper and the real in-memory stores.

```python
from tests.fakes import (
    CLIENT_ID,
    ISSUER,
    CountingTokens,
    FakeClock,
    FakeProvider,
    FakeVerifier,
    Signer,
    id_token_claims,
)
```

The fakes: constants, counting tokens, clock, fake provider and verifier, signer and the claim builder.

```python
CONFIG = LoginConfig(
    issuer=ISSUER,
    client_id=CLIENT_ID,
    allowed_extra_scopes=frozenset({"reports:read"}),
    pending_ttl_seconds=600,
    session_idle_seconds=900,
    session_absolute_seconds=28800,
    refresh_margin_seconds=30,
)
```

`CONFIG` is the flow's configuration for the tests: the fake issuer and client, only `reports:read` allowed, and 600, 900, 28,800 and 30 seconds for the five times.

```python
@pytest.fixture
def world():
    clock, signer = FakeClock(), Signer()
    provider = FakeProvider(signer, clock)
    sessions = InMemorySessionStore()
    service = LoginService(
        provider, FakeVerifier(signer), InMemoryPendingLoginStore(clock, 600), sessions, clock, CountingTokens(), CONFIG
    )
    return service, provider, sessions, clock, signer
```

The `world` fixture builds a clock, a signer, a fake provider, a real session store and the real `LoginService` over them, and returns the pieces together (the tests unpack what they need; `*_` takes the rest).

```python
def begin(service, provider, extra=()):
    """Start a login and play the user: returns the attempt id, the state and a code from the provider."""
    started = service.start(list(extra))
    return started.attempt_id, provider.last_authorization["state"], provider.issue_code()
```

`begin` starts a login and plays the user: it returns the attempt id, the state the provider saw and a one-time code from the provider.

```python
def test_start_sends_only_the_challenge_never_the_verifier(world):
    service, provider, *_ = world
    started = service.start([])
    sent = provider.last_authorization
    assert sent["code_challenge"]
    assert sent["state"] != sent["nonce"]
    assert started.max_age_seconds == 600
    verifier = next(iter(service._pending._items.values())).code_verifier
    assert challenge_for(verifier) == sent["code_challenge"]
    assert verifier not in started.authorization_url
```

Starting sends only the challenge. The fake provider received a challenge; the state and nonce differ; the cookie lifetime is 600. The test reads the stored verifier through private attributes (`service._pending._items`) and checks that its S256 challenge equals the one sent and that the verifier does not appear in the authorization address.

```python
def test_a_scope_outside_the_allow_list_is_not_requested(world):
    service, provider, *_ = world
    service.start(["admin", "reports:read"])
    assert provider.last_authorization["scope"] == "openid profile email reports:read"
```

Asking for `admin` and `reports:read` results in a request for only the base scopes plus `reports:read`.

```python
def test_a_full_sign_in_creates_a_session_whose_tokens_stay_on_the_server(world):
    service, provider, sessions, *_ = world
    attempt, state, code = begin(service, provider)
    issued = service.complete(attempt_id=attempt, state=state, code=code)
    assert issued.max_age_seconds == 28800
    session = sessions.get(hash_session_id(issued.raw_session_id))
    assert session is not None
    assert session.identity.subject == "user-1"
    assert session.identity.username == "demo-user"
    assert session.tokens.access_token.startswith("access-")
    assert session.tokens.refresh_token.startswith("refresh-")
    assert issued.raw_session_id not in (
        session.tokens.access_token,
        session.tokens.refresh_token,
        session.tokens.id_token,
    )
    assert "access-" not in repr(session)
    assert "refresh-" not in repr(session)
    assert [name for name, _ in provider.requests] == ["exchange"]
```

A full sign-in: the cookie lifetime is 28,800; the session in the store has the right subject and username; the tokens have the fake provider's prefixes; the raw session id is none of the tokens; the printed form of the session contains neither `access-` nor `refresh-` (they are hidden from `repr`); and the provider saw exactly one request, the exchange.

```python
@pytest.mark.parametrize(
    ("attempt", "state"),
    [(None, "s"), ("", "s"), ("a", None), ("a", ""), ("unknown-attempt", "whatever")],
)
def test_a_callback_not_tied_to_a_login_this_browser_started_is_refused_before_any_exchange(world, attempt, state):
    service, provider, *_ = world
    service.start([])
    with pytest.raises(StateMismatchError):
        service.complete(attempt_id=attempt, state=state, code="code")
    assert provider.requests == []
```

`parametrize` runs five bad callbacks: no attempt id, an empty attempt id, no state, an empty state and an unknown attempt id. Each raises `StateMismatchError`, and the provider received no request at all: nothing is exchanged for an unvalidated callback.

```python
def test_a_mismatched_state_is_refused_and_burns_the_attempt(world):
    service, provider, *_ = world
    attempt, state, code = begin(service, provider)
    with pytest.raises(StateMismatchError, match="state does not match"):
        service.complete(attempt_id=attempt, state="attacker-chosen-state", code=code)
    with pytest.raises(StateMismatchError, match="unknown or already used"):
        service.complete(attempt_id=attempt, state=state, code=code)
    assert provider.requests == []
```

A callback with the wrong state is refused with "state does not match", and it burns the attempt: the second try with the right state says "unknown or already used". The provider was never asked.

```python
def test_a_callback_cannot_be_replayed_once_it_succeeded(world):
    service, provider, *_ = world
    attempt, state, code = begin(service, provider)
    service.complete(attempt_id=attempt, state=state, code=code)
    with pytest.raises(StateMismatchError, match="already used"):
        service.complete(attempt_id=attempt, state=state, code=code)
```

After a successful callback, the same callback again says "already used".

```python
def test_a_login_attempt_expires(world):
    service, provider, _, clock, _ = world
    attempt, state, code = begin(service, provider)
    clock.advance(seconds=601)
    with pytest.raises(StateMismatchError):
        service.complete(attempt_id=attempt, state=state, code=code)
```

After 601 seconds the attempt has expired and the callback is refused.

```python
def test_a_callback_without_a_code_is_refused(world):
    service, provider, *_ = world
    attempt, state, _ = begin(service, provider)
    with pytest.raises(StateMismatchError, match="no authorization code"):
        service.complete(attempt_id=attempt, state=state, code=None)
```

A callback with no code is refused with "no authorization code".

```python
def test_a_code_cannot_be_exchanged_twice(world):
    service, provider, *_ = world
    attempt, state, code = begin(service, provider)
    service.complete(attempt_id=attempt, state=state, code=code)
    attempt2 = service.start([]).attempt_id
    with pytest.raises(ProviderError) as refused:
        service.complete(attempt_id=attempt2, state=provider.last_authorization["state"], code=code)
    assert refused.value.code == "invalid_grant"
```

The same code cannot be used by two logins: a second login presenting the old code gets a `ProviderError` with `invalid_grant`.

```python
def test_the_wrong_pkce_verifier_is_refused_by_the_provider(world):
    service, provider, *_ = world
    service.start([])
    code = provider.issue_code()
    with pytest.raises(ProviderError, match="PKCE verification failed"):
        provider.exchange_code(code=code, code_verifier="v" * 64)
```

The fake provider checks PKCE: exchanging the code with a wrong verifier raises "PKCE verification failed".

```python
@pytest.mark.parametrize(
    ("setup", "error", "reason"),
    [
        (
            lambda p: p.id_token_overrides.update(aud="another-client"),
            AudienceMismatchError,
            "audience claim does not match client id",
        ),
        (lambda p: p.id_token_overrides.update(exp=1), TokenExpiredError, "token has expired"),
        (lambda p: p.id_token_overrides.update(nonce="a-different-logins-nonce"), NonceMismatchError, "nonce mismatch"),
        (lambda p: setattr(p, "id_token_signer", Signer()), SignatureInvalidError, "signature verification failed"),
        (
            lambda p: p.id_token_overrides.update(at_hash="AAAAAAAAAAAAAAAAAAAAAA"),
            TokenValidationError,
            "access token hash",
        ),
    ],
)
```

`parametrize` runs five bad ID tokens built by changing what the fake provider puts in the token: a different audience; an expiry of 1 (long past); a different nonce; a different signing key; an `at_hash` that does not match. Each has its error class and reason text. (`lambda p: ...` is a one-line function.)

```python
def test_a_bad_id_token_is_rejected_with_its_own_reason_and_creates_no_session(world, setup, error, reason):
    service, provider, sessions, *_ = world
    setup(provider)
    attempt, state, code = begin(service, provider)
    with pytest.raises(error, match=reason):
        service.complete(attempt_id=attempt, state=state, code=code)
    assert sessions.count() == 0
```

For each, `complete` raises the named error with its own reason, and no session is created.

```python
def test_an_id_token_signed_with_an_unaccepted_algorithm_is_rejected(world):
    service, provider, sessions, *_ = world
    provider.id_token_factory = lambda nonce, _access: jwt.encode(
        id_token_claims(provider.clock, nonce=nonce), key="", algorithm="none", headers={"kid": provider.signer.kid}
    )
    attempt, state, code = begin(service, provider)
    with pytest.raises(UnsupportedAlgorithmError):
        service.complete(attempt_id=attempt, state=state, code=code)
    assert sessions.count() == 0
```

The provider is told to build an unsigned `none` token; `complete` raises `UnsupportedAlgorithmError` and no session exists.

```python
def test_a_token_response_without_an_id_token_is_refused(world):
    service, provider, *_ = world
    provider.omit_id_token = True
    attempt, state, code = begin(service, provider)
    with pytest.raises(ProviderError, match="no ID token"):
        service.complete(attempt_id=attempt, state=state, code=code)
```

A token response without an ID token is refused as "no ID token".

```python
def signed_in(world, extra=()):
    service, provider, _sessions, _clock, _ = world
    attempt, state, code = begin(service, provider, extra)
    issued = service.complete(attempt_id=attempt, state=state, code=code)
    return issued, service.resolve(issued.raw_session_id)
```

`signed_in` is a helper that does a full sign-in and returns the issued session and the resolved session.

```python
def test_resolve_returns_the_session_until_it_is_idle_too_long(world):
    service, _, _, clock, _ = world
    issued, _ = signed_in(world)
    clock.advance(minutes=14)
    assert service.resolve(issued.raw_session_id) is not None
    clock.advance(minutes=14)  # 14 minutes after the last use: still inside 15
    assert service.resolve(issued.raw_session_id) is not None
    clock.advance(minutes=16)
    assert service.resolve(issued.raw_session_id) is None
```

Idle expiry: after 14 minutes the session resolves (and its last-seen time moves); after 14 more it still resolves; after 16 more minutes without use it does not (more than the 15-minute idle limit).

```python
def test_a_session_ends_at_its_absolute_lifetime_even_with_constant_use(world):
    service, _, _, clock, _ = world
    issued, _ = signed_in(world)
    for _ in range(34):
        clock.advance(minutes=14)
        service.resolve(issued.raw_session_id)
    clock.advance(minutes=14)
    assert service.resolve(issued.raw_session_id) is None
```

Absolute lifetime: 34 uses every 14 minutes keep the session alive; the next use, at 8 hours 10 minutes, finds it dead (the limit is 8 hours).

```python
def test_unknown_and_empty_cookie_values_resolve_to_nothing(world):
    service, *_ = world
    assert service.resolve(None) is None
    assert service.resolve("") is None
    assert service.resolve("nope") is None
```

`None`, an empty value and an unknown value resolve to nothing.

```python
def test_refresh_rotates_the_refresh_token_and_the_old_one_stops_working(world):
    service, provider, sessions, *_ = world
    _, session = signed_in(world)
    old = session.tokens.refresh_token
    renewed = service.refresh(session)
    assert renewed.tokens.refresh_token != old
    assert sessions.get(session.session_id_hash).tokens.refresh_token == renewed.tokens.refresh_token
    with pytest.raises(ProviderError) as reused:
        provider.refresh(old)
    assert reused.value.code == "invalid_grant"
    assert renewed.tokens.id_token == session.tokens.id_token  # a refresh response carries none; the login's is kept
```

Refresh rotates the token: the new refresh token differs, the store holds the new one, the old one now fails at the provider with `invalid_grant`, and the ID token from the login is kept because a refresh response carries none.

```python
def test_a_refused_refresh_drops_the_session(world):
    service, provider, sessions, *_ = world
    _, session = signed_in(world)
    provider.refresh_tokens[session.tokens.refresh_token] = False
    with pytest.raises(ProviderError):
        service.refresh(session)
    assert sessions.count() == 0
```

If the provider refuses the refresh token, `refresh` raises and the session is dropped.

```python
def test_refreshing_an_ended_session_is_refused(world):
    service, _, sessions, *_ = world
    _, session = signed_in(world)
    sessions.delete(session.session_id_hash)
    with pytest.raises(SessionNotFoundError):
        service.refresh(session)
```

Refreshing a session that already ended raises `SessionNotFoundError`.

```python
def test_the_access_token_is_refreshed_only_when_it_is_about_to_expire(world):
    service, provider, _, clock, _ = world
    issued, session = signed_in(world)
    token, same = service.access_token(session)
    assert token == session.tokens.access_token
    assert same.tokens == session.tokens
    clock.advance(seconds=100)  # 20 s left of 120, inside the 30 s margin
    live = service.resolve(issued.raw_session_id)
    assert live is not None
    token_after, renewed = service.access_token(live)
    assert token_after != token
    assert renewed.tokens.refresh_token != session.tokens.refresh_token
    assert [name for name, _ in provider.requests].count("refresh") == 1
```

While the access token has time left, `access_token` returns it unchanged. After 100 seconds (20 left of 120, inside the 30-second margin) it refreshes: the token and the refresh token change, and the provider saw exactly one refresh.

```python
def test_sign_out_removes_the_session_and_revokes_the_refresh_token(world):
    service, provider, sessions, *_ = world
    issued, session = signed_in(world)
    assert service.sign_out(issued.raw_session_id) is True
    assert sessions.count() == 0
    assert provider.refresh_tokens[session.tokens.refresh_token] is False
    assert service.resolve(issued.raw_session_id) is None
```

Sign-out returns true, empties the store, shows the provider marked the refresh token invalid (revoked) and the cookie value resolves to nothing.

```python
def test_sign_out_ends_the_local_session_even_when_revocation_fails(world):
    service, provider, sessions, *_ = world
    issued, _ = signed_in(world)

    def broken(token):
        raise ProviderError("server_error")

    provider.revoke = broken
    assert service.sign_out(issued.raw_session_id) is False
    assert sessions.count() == 0
```

If revocation fails (the provider's `revoke` is replaced by a function that raises), sign-out returns false but the local session is gone.

```python
def test_sign_out_without_a_session_is_harmless(world):
    service, *_ = world
    assert service.sign_out(None) is False
    assert service.sign_out("never-issued") is False
```

Signing out with no cookie or an unknown one is harmless and returns false.

```python
def test_csrf_comparison(world):
    service, *_ = world
    _, session = signed_in(world)
    assert service.csrf_valid(session, session.csrf_token)
    assert not service.csrf_valid(session, "wrong")
    assert not service.csrf_valid(session, None)
```

The right CSRF token is valid; a wrong one and `None` are not.

```python
def test_the_session_id_is_stored_only_as_a_hash(world):
    _, _, sessions, *_ = world
    issued, session = signed_in(world)
    assert session.session_id_hash == hash_session_id(issued.raw_session_id) != issued.raw_session_id
    assert sessions.get(issued.raw_session_id) is None
```

The stored id is the hash, not the raw value, and looking up by the raw value finds nothing.

```python
def test_old_sessions_are_purged_when_a_new_one_starts(world):
    _service, _provider, sessions, clock, _ = world
    signed_in(world)
    clock.advance(hours=1)
    signed_in(world)
    assert sessions.count() == 1
```

Signing in an hour later purges the old session: the store ends with one.

```python
def test_a_granted_extra_scope_is_recorded_on_the_session(world):
    _, provider, *_ = world
    provider.granted_scope = "openid reports:read"
    _, session = signed_in(world, extra=["reports:read"])
    assert "reports:read" in session.scopes
    assert timedelta(seconds=120) == session.tokens.access_expires_at - session.created_at
```

When the provider grants `openid reports:read`, the session's scopes include `reports:read`, and the access token is valid for 120 seconds from creation.

### Line by line: `tests/unit/test_oidc_provider.py`

These tests exercise the real provider adapter without a network. `httpx.MockTransport` is a fake network for the HTTP client: you give it a function that receives each request and returns a response.

```python
import json
from urllib.parse import parse_qs, urlsplit
```

Imports: `json` and URL helpers (`parse_qs` reads form or query text, `urlsplit` cuts an address into parts).

```python
import httpx
import pytest
```

`httpx` and `pytest`.

```python
from oidc_login.domain.errors import ProviderError, ProviderUnavailableError
from oidc_login.infrastructure.oidc_provider import OidcProvider
from tests.fakes import CLIENT_ID, ISSUER, REDIRECT_URI
```

The two provider errors, the adapter and the shared constants.

```python
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    "userinfo_endpoint": f"{ISSUER}/protocol/openid-connect/userinfo",
    "revocation_endpoint": f"{ISSUER}/protocol/openid-connect/revoke",
}
```

`DISCOVERY` is a valid discovery document for the fake issuer with the six required fields.

```python
TOKEN_BODY = {"access_token": "a", "refresh_token": "r", "id_token": "i", "expires_in": 120, "scope": "openid profile"}
```

`TOKEN_BODY` is a valid token endpoint answer: access, refresh and ID tokens, 120 seconds and a scope.

```python
def provider_with(handler, sleeps=None):
    transport = httpx.MockTransport(handler)
    return OidcProvider(
        issuer=ISSUER,
        discovery_base=ISSUER,
        client_id=CLIENT_ID,
        client_secret="the-secret",
        redirect_uri=REDIRECT_URI,
        http=httpx.Client(transport=transport),
        sleep=(sleeps.append if sleeps is not None else (lambda _: None)),
    )
```

`provider_with(handler, sleeps)` builds the adapter on a client that uses the mock transport. The `sleep` function is either a list's `append` (so the test can see the delays) or a function that does nothing, so retries do not slow the tests.

```python
def routes(**overrides):
    table = {
        "/.well-known/openid-configuration": (200, DISCOVERY),
        "/protocol/openid-connect/certs": (200, {"keys": []}),
        "/protocol/openid-connect/token": (200, TOKEN_BODY),
        "/protocol/openid-connect/revoke": (200, {}),
        "/protocol/openid-connect/userinfo": (200, {"sub": "user-1"}),
    }
    table.update(overrides)
    seen = []
```

`routes(**overrides)` builds a table from path to (status, JSON body) with defaults for discovery, keys, token, revoke and userinfo; overrides replace entries. `seen` collects every request.

```python
    def handler(request):
        path = request.url.path.removeprefix("/realms/demo")
        seen.append(request)
        status, body = table[path]
        return httpx.Response(status, json=body)

    return handler, seen
```

The handler removes the `/realms/demo` prefix of the path, records the request, looks up the answer and returns it as an `httpx.Response` with a JSON body. It returns the handler and the list.

```python
def test_the_discovery_document_is_fetched_once_and_cached():
    handler, seen = routes()
    provider = provider_with(handler)
    assert provider.metadata().token_endpoint.endswith("/token")
    provider.metadata()
    assert len(seen) == 1
```

The discovery document is fetched once and cached: two calls to `metadata()` made one request.

```python
def test_a_discovery_document_for_another_issuer_is_refused():
    handler, _ = routes(
        **{"/.well-known/openid-configuration": (200, {**DISCOVERY, "issuer": "http://evil.example.test/realms/demo"})}
    )
    with pytest.raises(ProviderUnavailableError, match="does not match OIDC_ISSUER"):
        provider_with(handler).metadata()
```

A discovery document whose issuer is another host is refused with the message "does not match OIDC_ISSUER".

```python
def test_a_discovery_document_missing_an_endpoint_is_refused():
    handler, _ = routes(
        **{"/.well-known/openid-configuration": (200, {k: v for k, v in DISCOVERY.items() if k != "jwks_uri"})}
    )
    with pytest.raises(ProviderUnavailableError, match="jwks_uri"):
        provider_with(handler).metadata()
```

A document without `jwks_uri` is refused, naming it.

```python
def test_gets_are_retried_with_backoff_and_then_succeed():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=DISCOVERY)

    sleeps: list[float] = []
    assert provider_with(handler, sleeps).metadata().issuer == ISSUER
    assert len(attempts) == 3
    assert sleeps == [0.2, 0.5]
```

A GET is retried with backoff: the fake answers 503 twice and then 200; the metadata arrives after three attempts, and the sleeps were 0.2 and 0.5 seconds.

```python
def test_gets_give_up_after_the_last_retry_with_a_clear_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailableError, match="could not fetch"):
        provider_with(handler).metadata()
```

When every try fails with a connection error, the adapter gives up with "could not fetch".

```python
def test_a_client_error_on_a_get_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(ProviderUnavailableError, match="404"):
        provider_with(handler).metadata()
    assert len(calls) == 1
```

A 404 is a client error and is not retried: one call, and the message names 404.

```python
def test_the_authorization_url_asks_for_the_code_flow_with_s256_and_the_one_redirect_uri():
    handler, _ = routes()
    url = provider_with(handler).authorization_url(
        state="s", nonce="n", code_challenge="c", scope="openid reports:read"
    )
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert parts.path.endswith("/protocol/openid-connect/auth")
    assert query == {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "openid reports:read",
        "state": "s",
        "nonce": "n",
        "code_challenge": "c",
        "code_challenge_method": "S256",
    }
    assert "the-secret" not in url  # the client secret never goes through the browser
```

The authorization address has the path of the authorization endpoint and exactly the eight query values: client id, `response_type=code`, the one redirect address, the scope, state, nonce, challenge and `S256`. The client secret is not in it: it never goes through the browser.

```python
def test_the_code_exchange_is_a_server_to_server_post_with_the_verifier_and_the_secret_in_the_body():
    handler, seen = routes()
    response = provider_with(handler).exchange_code(code="the-code", code_verifier="v" * 64)
    request = seen[-1]
    form = parse_qs(request.content.decode())
    assert request.method == "POST"
    assert request.url.path.endswith("/token")
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["the-code"]
    assert form["code_verifier"] == ["v" * 64]
    assert form["client_secret"] == ["the-secret"]
    assert form["redirect_uri"] == [REDIRECT_URI]
    assert (response.access_token, response.refresh_token, response.id_token, response.expires_in) == (
        "a",
        "r",
        "i",
        120,
    )
```

The code exchange is a server-to-server POST. The form body has `grant_type=authorization_code`, the code, the verifier, the client secret and the redirect address; the answer is turned into a `TokenResponse` with the four fields.

```python
def test_the_providers_error_code_is_carried_in_the_exception_and_the_post_is_not_retried():
    handler, seen = routes(
        **{"/protocol/openid-connect/token": (400, {"error": "invalid_grant", "error_description": "Code not valid"})}
    )
    with pytest.raises(ProviderError) as refused:
        provider_with(handler).exchange_code(code="used", code_verifier="v" * 64)
    assert refused.value.code == "invalid_grant"
    assert refused.value.description == "Code not valid"
    assert sum(request.method == "POST" for request in seen) == 1
```

A 400 with `invalid_grant` becomes a `ProviderError` carrying the code and the description, and only one POST was made: back-channel POSTs are never retried.

```python
def test_an_error_body_that_is_not_json_still_yields_a_provider_error():
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(502, text="<html>bad gateway</html>")
            if request.method == "POST"
            else httpx.Response(200, json=DISCOVERY)
        )
    )
    provider = OidcProvider(
        issuer=ISSUER,
        discovery_base=ISSUER,
        client_id=CLIENT_ID,
        client_secret="s",
        redirect_uri=REDIRECT_URI,
        http=httpx.Client(transport=transport),
    )
    with pytest.raises(ProviderError) as refused:
        provider.refresh("r")
    assert refused.value.code == "http_502"
```

An error body that is not JSON (a 502 page of HTML) still gives a `ProviderError` with the code `http_502`. This test builds the transport inline: a POST answers 502 text, a GET answers the discovery document.

```python
def test_a_token_response_missing_fields_is_an_invalid_response():
    handler, _ = routes(**{"/protocol/openid-connect/token": (200, {"access_token": "a"})})
    with pytest.raises(ProviderError) as refused:
        provider_with(handler).refresh("r")
    assert refused.value.code == "invalid_response"
```

A token answer missing fields (only `access_token`) is an `invalid_response` error.

```python
def test_a_network_failure_on_a_post_is_provider_unavailable():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=DISCOVERY)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ProviderUnavailableError, match="ReadTimeout"):
        provider_with(handler).refresh("r")
```

A timeout on a POST becomes `ProviderUnavailableError`, with only the error's class name `ReadTimeout` in the message.

```python
def test_refresh_and_revoke_send_the_expected_forms():
    handler, seen = routes()
    provider = provider_with(handler)
    provider.refresh("old-refresh")
    provider.revoke("old-refresh")
    refresh_form, revoke_form = (parse_qs(request.content.decode()) for request in seen[-2:])
    assert refresh_form["grant_type"] == ["refresh_token"]
    assert refresh_form["refresh_token"] == ["old-refresh"]
    assert revoke_form["token"] == ["old-refresh"]
    assert revoke_form["token_type_hint"] == ["refresh_token"]
```

Refresh sends `grant_type=refresh_token` with the token; revoke sends `token` and `token_type_hint=refresh_token`.

```python
def test_a_failed_revocation_raises_the_providers_error():
    handler, _ = routes(**{"/protocol/openid-connect/revoke": (400, {"error": "unauthorized_client"})})
    with pytest.raises(ProviderError, match="unauthorized_client"):
        provider_with(handler).revoke("r")
```

A failed revocation raises the provider's error.

```python
def test_userinfo_sends_the_bearer_token_and_returns_the_claims():
    handler, seen = routes()
    assert provider_with(handler).userinfo("the-access-token") == {"sub": "user-1"}
    assert seen[-1].headers["authorization"] == "Bearer the-access-token"
```

Userinfo sends the header `Authorization: Bearer <token>` and returns the claims.

```python
def test_userinfo_errors_are_mapped():
    handler, _ = routes(**{"/protocol/openid-connect/userinfo": (401, {"error": "invalid_token"})})
    with pytest.raises(ProviderError, match="invalid_token"):
        provider_with(handler).userinfo("expired")

    def down(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=DISCOVERY)
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailableError):
        provider_with(down).userinfo("x")
```

A 401 from userinfo becomes a `ProviderError`; a connection failure becomes `ProviderUnavailableError`.

```python
def test_jwks_are_fetched_from_the_discovered_uri_and_the_client_can_be_closed():
    handler, seen = routes(**{"/protocol/openid-connect/certs": (200, {"keys": [{"kid": "k"}]})})
    provider = provider_with(handler)
    assert provider.jwks() == {"keys": [{"kid": "k"}]}
    assert json.loads(json.dumps(DISCOVERY))["jwks_uri"].endswith("/certs")
    assert len(seen) == 2
    provider.close()
```

The key set is fetched from the discovered address: two requests were made (discovery and keys), the result is the fake key list, and the client can be closed.

### Line by line: `tests/unit/test_http_app.py`

```python
"""The HTTP layer over a fake provider: cookies, headers, callback error mapping, CSRF and scope checks."""
```

The docstring: the HTTP layer over a fake provider, covering cookies, headers, callback error mapping, CSRF and scope checks.

```python
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
```

Type hints kept as text; `Any`, URL helpers and `pytest`.

```python
from oidc_login.application.login_flow import LoginConfig, LoginService
from oidc_login.domain.errors import ProviderError
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
from oidc_login.infrastructure.settings import Settings
from oidc_login.interfaces.composition import Container
from oidc_login.interfaces.http.app import create_app
from oidc_login.interfaces.http.security import CONTENT_SECURITY_POLICY, LOGIN_COOKIE, SESSION_COOKIE
from oidc_login.interfaces.scripted_browser import AppBrowser
```

Imports of the flow, the error, the real in-memory stores, the settings, the container, the app factory, the policy and cookie names, and the scripted app browser.

```python
from tests.fakes import CLIENT_ID, ISSUER, REDIRECT_URI, CountingTokens, FakeClock, FakeProvider, FakeVerifier, Signer
```

The shared fakes.

```python
SETTINGS = Settings.from_environment(
    {
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": CLIENT_ID,
        "OIDC_CLIENT_SECRET": "unit-test-secret",
        "OIDC_REDIRECT_URI": REDIRECT_URI,
        "APP_ENV": "test",
    }
)
```

`SETTINGS` are built once at import from a small environment in `test` mode with a placeholder secret.

```python
@pytest.fixture
def world():
    clock, signer = FakeClock(), Signer()
    provider = FakeProvider(signer, clock)
    sessions = InMemorySessionStore()
    flow = LoginService(
        provider,
        FakeVerifier(signer),
        InMemoryPendingLoginStore(clock, 600),
        sessions,
        clock,
        CountingTokens(),
        LoginConfig(ISSUER, CLIENT_ID, frozenset({"reports:read"})),
    )
    container: Any = Container(settings=SETTINGS, provider=provider, flow=flow, sessions=sessions)  # type: ignore[arg-type]
    return create_app(container), provider, sessions
```

The `world` fixture builds the fake provider and the real flow over it (with the same allow-list), wraps them in a `Container` (`# type: ignore[arg-type]` accepts the fake provider where the real adapter is expected) and returns the Flask app, the provider and the session store.

```python
def sign_in(world, scope=None):
    """Drive the whole round trip with the fake provider; returns the browser and the callback response."""
    app, provider, _ = world
```

`sign_in` is a helper that drives the whole round trip with the fake provider and returns the browser, the callback response and the start response. It records the granted scope when one is asked for.

```python
    if scope:
        provider.granted_scope = f"openid {scope}"
    browser = AppBrowser(app)
    start = browser.get("/login" + (f"?scope={scope}" if scope else ""))
    code = provider.issue_code()
    state = provider.last_authorization["state"]
    return browser, browser.get(f"/callback?code={code}&state={state}"), start
```

It opens `/login`, asks the provider for a code, takes the state the provider saw and calls `/callback` with them.

```python
def test_login_redirects_to_the_provider_and_sets_a_short_lived_attempt_cookie(world):
    app, provider, _ = world
    response = AppBrowser(app).get("/login")
    assert response.status_code == 302
    assert response.headers["Location"].startswith(f"{ISSUER}/auth?")
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{LOGIN_COOKIE}=")
    for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=600"):
        assert attribute in cookie
    assert "Domain" not in cookie
    assert provider.last_authorization["state"] in response.headers["Location"]
```

`/login` redirects (302) to the provider's address and sets the login-attempt cookie, which is HttpOnly, Secure, SameSite=Lax, `Path=/` and has `Max-Age=600`, with no `Domain`. The state is in the address.

```python
def test_the_callback_creates_an_opaque_session_cookie_and_clears_the_attempt_cookie(world):
    _, response, _ = sign_in(world)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    cookies = response.headers.getlist("Set-Cookie")
    session_cookie = next(c for c in cookies if c.startswith(SESSION_COOKIE))
    for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/"):
        assert attribute in session_cookie
    value = session_cookie.split("=", 1)[1].split(";", 1)[0]
    assert "." not in value
    assert len(value) >= 32
    assert any(c.startswith(f"{LOGIN_COOKIE}=;") for c in cookies)
```

The callback redirects to `/`; the session cookie has the four attributes, its value has no dot (not a JWT) and is at least 32 characters; and the login-attempt cookie is cleared (`__Host-login=;`).

```python
def test_no_token_ever_reaches_the_browser(world):
    _, _provider, sessions = world
    browser, callback, _ = sign_in(world)
    session = next(iter(sessions._items.values()))
    secrets_held = [session.tokens.access_token, session.tokens.refresh_token, session.tokens.id_token]
    pages = [callback, browser.get("/"), browser.get("/me"), browser.get("/reports")]
    for page in pages:
        blob = page.get_data(as_text=True) + str(dict(page.headers))
        assert all(secret not in blob for secret in secrets_held)
```

No token ever reaches the browser: after sign-in, the three tokens held on the server do not appear in the body or headers of the callback, the home page, `/me` or `/reports`.

```python
def test_every_response_carries_the_security_headers(world):
    app, *_ = world
    browser = AppBrowser(app)
    for path in ("/", "/login", "/healthz", "/me", "/nope", "/static/style.css"):
        headers = browser.get(path).headers
        assert headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "max-age" in headers["Strict-Transport-Security"]
        assert path.startswith("/static") or headers["Cache-Control"] == "no-store"  # pages carry tokens' results
```

For six paths including an unknown one and the stylesheet, every response has the CSP, `no-referrer`, `nosniff`, `DENY` and an HSTS `max-age`; every path except static files also has `Cache-Control: no-store`.

```python
@pytest.mark.parametrize(
    ("query", "status"),
    [("", 400), ("?error=access_denied", 400), ("?code=x", 400), ("?state=x", 400), ("?code=x&state=y", 400)],
)
def test_a_callback_without_a_valid_login_attempt_is_a_generic_400_and_sets_no_session(world, query, status):
    app, *_ = world
    response = AppBrowser(app).get(f"/callback{query}")
    assert response.status_code == status
    assert SESSION_COOKIE not in response.headers.get("Set-Cookie", "")
    assert "error" not in response.get_data(as_text=True).lower().replace("sign-in failed", "")
```

Five bad callbacks (nothing, an `error` parameter, only a code, only a state, a code and state with no attempt cookie) each give 400, set no session cookie and show a generic page whose text contains no word "error" apart from the "Sign-in failed" title.

```python
def test_a_mismatched_state_is_refused(world):
    app, provider, sessions = world
    browser = AppBrowser(app)
    browser.get("/login")
    code = provider.issue_code()
    response = browser.get(f"/callback?code={code}&state=attacker-state")
    assert response.status_code == 400
    assert sessions.count() == 0
```

A mismatched state gives 400 and no session.

```python
def test_a_callback_from_another_browser_is_refused_even_with_a_valid_code_and_state(world):
    app, provider, sessions = world
    AppBrowser(app).get("/login")  # the attacker starts a login in their own browser...
    code, state = provider.issue_code(), provider.last_authorization["state"]
    victim = AppBrowser(app)  # ...and tricks the victim's browser into completing it: no attempt cookie
    assert victim.get(f"/callback?code={code}&state={state}").status_code == 400
    assert sessions.count() == 0
```

Login CSRF: an attacker starts a login in their own browser and gets a valid code and state; the victim's browser, which has no attempt cookie, is sent to the callback: 400 and no session.

```python
def test_a_replayed_callback_is_refused(world):
    _app, _provider, _ = world
    browser, first, _ = sign_in(world)
    assert first.status_code == 302
    assert (
        browser.get(first.request.full_path).status_code == 400
    )  # the attempt cookie was cleared and the state consumed
```

A replayed callback is refused: after the first success the attempt cookie was cleared and the state consumed, so the same request again gives 400.

```python
def test_the_provider_refusing_the_code_is_a_400_and_a_forged_token_a_401(world):
    app, provider, _ = world
    browser = AppBrowser(app)
    browser.get("/login")
    assert browser.get(f"/callback?code=never-issued&state={provider.last_authorization['state']}").status_code == 400
    forger = Signer()
    provider.id_token_signer = forger
    browser.get("/login")
    code, state = provider.issue_code(), provider.last_authorization["state"]
    assert browser.get(f"/callback?code={code}&state={state}").status_code == 401
```

A code the provider never issued gives 400. A token signed by a different key gives 401.

```python
def test_a_provider_outage_during_sign_in_is_a_502(world):
    app, provider, _ = world

    def down(**_: Any) -> Any:
        from oidc_login.domain.errors import ProviderUnavailableError

        raise ProviderUnavailableError("down")

    browser = AppBrowser(app)
    browser.get("/login")
    provider.exchange_code = down
    assert (
        browser.get(f"/callback?code={provider.issue_code()}&state={provider.last_authorization['state']}").status_code
        == 502
    )
```

A provider outage during the code exchange (the exchange method is replaced by a function that raises `ProviderUnavailableError`) gives 502.

```python
def test_me_shows_the_identity_and_scopes_but_no_tokens(world):
    browser, *_ = sign_in(world)
    body = browser.get("/me").get_json()
    assert body["username"] == "demo-user"
    assert body["subject"] == "user-1"
    assert set(body) == {"subject", "username", "scopes", "session_expires_at"}
```

`/me` returns the username and subject and exactly the four keys, no tokens.

```python
def test_routes_that_need_a_session_answer_401_without_one(world):
    app, *_ = world
    browser = AppBrowser(app)
    for method, path in (("GET", "/me"), ("GET", "/api/profile"), ("POST", "/refresh"), ("GET", "/reports")):
        assert browser.request(method, path).status_code == 401, path
```

Without a session, `/me`, `/api/profile`, `/refresh` and `/reports` each answer 401.

```python
def test_the_profile_route_calls_userinfo_with_the_access_token_held_on_the_server(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    body = browser.get("/api/profile").get_json()
    assert body == {"email": "demo-user@example.test", "subject": "user-1", "username": "demo-user"}
    session = next(iter(sessions._items.values()))
    assert ("userinfo", {"access_token": session.tokens.access_token}) in provider.requests
```

`/api/profile` returns the email, subject and username, and the provider saw a userinfo call carrying the access token held on the server.

```python
def test_refresh_needs_the_csrf_token_and_then_rotates_the_refresh_token(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    before = next(iter(sessions._items.values()))
    assert browser.post("/refresh").status_code == 403
    assert browser.post("/refresh", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    response = browser.post("/refresh", headers={"X-CSRF-Token": before.csrf_token})
    assert response.status_code == 200
    assert response.get_json()["refreshed"] is True
    after = next(iter(sessions._items.values()))
    assert after.tokens.refresh_token != before.tokens.refresh_token
    with pytest.raises(ProviderError):
        provider.refresh(before.tokens.refresh_token)
```

`/refresh` without a token or with a wrong token gives 403; with the right token it gives 200 and `refreshed: true`; the stored refresh token changed and the old one is refused at the provider.

```python
def test_a_session_whose_refresh_token_was_revoked_gets_401_and_is_dropped(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    session = next(iter(sessions._items.values()))
    provider.refresh_tokens[session.tokens.refresh_token] = False
    response = browser.post("/refresh", headers={"X-CSRF-Token": session.csrf_token})
    assert response.status_code == 401
    assert sessions.count() == 0
```

If the refresh token was revoked at the provider, `/refresh` gives 401 and the session is dropped.

```python
def test_logout_needs_the_csrf_token_ends_the_session_and_revokes_the_refresh_token(world):
    _, provider, sessions = world
    browser, *_ = sign_in(world)
    session = next(iter(sessions._items.values()))
    assert browser.post("/logout").status_code == 403
    assert sessions.count() == 1  # a forged logout did nothing
    response = browser.post("/logout", data={"csrf_token": session.csrf_token})
    assert response.status_code == 303
    assert f"{SESSION_COOKIE}=;" in response.headers["Set-Cookie"]
    assert sessions.count() == 0
    assert provider.refresh_tokens[session.tokens.refresh_token] is False
    assert browser.get("/me").status_code == 401
```

Logout without the CSRF token gives 403 and the session survives (a forged logout did nothing). With the token it gives 303, clears the cookie, empties the store, revokes the refresh token at the provider and `/me` then gives 401.

```python
def test_logout_without_a_session_is_a_harmless_redirect(world):
    app, *_ = world
    assert AppBrowser(app).post("/logout").status_code == 303
```

Logout without a session is a harmless 303 redirect.

```python
def test_the_reports_route_needs_the_elevated_scope(world):
    browser, *_ = sign_in(world)
    denied = browser.get("/reports")
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "insufficient_scope"
    elevated, *_ = sign_in(world, scope="reports:read")
    assert elevated.get("/reports").status_code == 200
```

A plain sign-in gets 403 from `/reports` with the code `insufficient_scope`; a sign-in that asked for `reports:read` gets 200.

```python
def test_home_page_changes_with_the_session_and_html_escapes_the_username(world):
    app, _provider, _sessions = world
    anonymous = AppBrowser(app).get("/").get_data(as_text=True)
    assert "Sign in" in anonymous
    assert "reports access" in anonymous
    browser, *_ = sign_in(world)
    page = browser.get("/").get_data(as_text=True)
    assert "demo-user" in page
    assert 'name="csrf_token"' in page
```

The home page shows "Sign in" and the reports link when signed out; after sign-in it shows the username and a CSRF form field.

```python
def test_health_and_readiness(world):
    app, provider, _ = world
    browser = AppBrowser(app)
    assert browser.get("/healthz").get_json() == {"status": "ok"}
    assert browser.get("/readyz").status_code == 200
    provider.unavailable = True
    assert browser.get("/readyz").status_code == 503
```

Health: `/healthz` is `ok`; `/readyz` is 200 while the provider is up and 503 when it is down.

```python
def test_unknown_routes_and_an_oversized_body_use_the_json_error_shape(world):
    app, *_ = world
    assert AppBrowser(app).get("/nope").get_json()["error"] == "not_found"
    browser, *_ = sign_in(world)
    oversized = browser.post("/logout", data={"csrf_token": "x" * 20_000})
    assert oversized.status_code == 413
    assert oversized.get_json()["error"] == "request_entity_too_large"
```

An unknown path gives the JSON `not_found`. A 20,000-character field is over the 16 KiB limit: 413 with the code `request_entity_too_large`.

```python
def test_an_unexpected_error_leaks_nothing(world):
    app, *_ = world

    @app.get("/boom")
    def boom():
        raise RuntimeError("internal detail")

    response = AppBrowser(app).get("/boom")
    assert response.status_code == 500
    assert "internal detail" not in response.get_data(as_text=True)
```

A route added by the test that raises an error with the text "internal detail" gives 500 and the text is not in the body.

```python
def test_the_authorization_url_the_browser_is_sent_to_matches_the_flow(world):
    app, _provider, _ = world
    location = AppBrowser(app).get("/login?scope=reports:read&scope=admin").headers["Location"]
    query = parse_qs(urlsplit(location).query)
    assert query["scope"] == ["openid profile email reports:read"]
```

`/login?scope=reports:read&scope=admin` redirects to an address whose scope is `openid profile email reports:read`: `admin` was dropped.

### Line by line: `tests/integration/test_code_flow.py`

These tests need the real identity provider, Keycloak (`make up`), and carry the marker `integration`. They reuse the demo's `Scenario` class: each test calls one step of the scenario and asserts on what it reports.

```python
"""Step 2: the authorization code flow with PKCE, with the token exchange on the server."""
```

The docstring: step 2, the authorization code flow with PKCE, with the token exchange on the server.

```python
import httpx
import pytest

from oidc_login.interfaces.demo_cli import Scenario
```

Imports: `httpx` (for the request type), `pytest` and `Scenario`.

```python
pytestmark = pytest.mark.integration
```

The `integration` marker for the whole file.

```python
def test_the_authorization_request_carries_state_nonce_and_an_s256_challenge_and_no_secret(scenario: Scenario):
    step, _ = scenario.start_login(scenario.new_browser())
    assert step.passed, step.detail
```

The `scenario` fixture (from `conftest.py`) provides a fresh app and scripted browsers. `start_login` returns a step; its `passed` flag must be true, and the message after the comma, its detail, is printed if not.

```python
def test_the_user_authenticates_at_the_provider_and_comes_back_to_the_registered_uri(scenario: Scenario):
    _, location = scenario.start_login(scenario.new_browser())
    step, back = scenario.authenticate(location)
    assert step.passed, step.detail
    assert back.startswith(scenario.settings.redirect_uri)
    assert "access_token" not in back
    assert "id_token" not in back
```

The user authenticates at the provider and is sent back to the registered redirect address; the redirect address contains no `access_token` or `id_token` (tokens never travel through the browser in the code flow).

```python
def test_a_full_sign_in_works_and_the_browser_receives_only_an_opaque_cookie(scenario: Scenario):
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    step = scenario.complete_login(browser, back)
    assert step.passed, step.detail
```

A full sign-in works and the browser receives only an opaque cookie.

```python
def test_the_token_exchange_is_one_server_to_server_post_with_the_verifier_and_the_secret(scenario: Scenario):
    seen: list[httpx.Request] = []
    scenario.container.provider._http.event_hooks["request"].append(seen.append)
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    scenario.complete_login(browser, back)
    exchanges = [r for r in seen if r.method == "POST" and r.url.path.endswith("/token")]
    assert len(exchanges) == 1
    body = exchanges[0].content.decode()
    assert "grant_type=authorization_code" in body
    assert "code_verifier=" in body
    assert "client_secret=" in body
    assert str(exchanges[0].url).startswith(scenario.settings.issuer)  # the app called the provider directly
```

The test adds a function to the provider adapter's HTTP client that records every request (`event_hooks["request"]` is a list of functions httpx calls before sending). After a full sign-in, exactly one POST to the token endpoint was made. Its body contains `grant_type=authorization_code`, `code_verifier=` and `client_secret=`, and the address starts with the issuer: the app called the provider directly, server to server.

### Line by line: `tests/integration/test_flow_protections.py`

```python
"""Step 4: the protections the standard warns about, each shown by what is refused."""
```

The docstring: step 4, the protections the standard warns about, each shown by what is refused.

```python
import pytest

from oidc_login.interfaces.demo_cli import Scenario
```

Imports.

```python
pytestmark = pytest.mark.integration
```

The `integration` marker.

```python
def test_a_callback_with_a_mismatched_state_is_refused(scenario: Scenario):
    step = scenario.mismatched_state()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0
```

A callback with a mismatched state is refused and no session exists.

```python
def test_a_valid_callback_in_a_browser_that_did_not_start_the_login_is_refused(scenario: Scenario):
    step = scenario.login_csrf()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0
```

A valid callback in a browser that did not start the login is refused (login CSRF) and no session exists.

```python
def test_a_successful_callback_cannot_be_replayed(scenario: Scenario):
    step = scenario.replayed_callback()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 1  # the first use created the only session
```

A successful callback cannot be replayed; the first use created the only session.

```python
def test_the_provider_refuses_lookalike_redirect_uris_before_the_app_sees_anything(scenario: Scenario):
    step = scenario.lookalike_redirect_uri()
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0
```

The real provider refuses look-alike redirect addresses before the app sees anything.

```python
def test_a_code_can_be_exchanged_only_once(scenario: Scenario):
    step = scenario.code_reuse()
    assert step.passed, step.detail
    assert "invalid_grant" in step.detail
```

A code can be exchanged once; the detail names `invalid_grant`.

```python
def test_a_code_is_useless_without_the_pkce_verifier(scenario: Scenario):
    step = scenario.wrong_pkce_verifier()
    assert step.passed, step.detail
    assert "invalid_grant" in step.detail
```

A code is useless without the right PKCE verifier; the detail names `invalid_grant`.

### Line by line: `tests/integration/test_provider_setup.py`

```python
"""Step 1: the provider is running, discoverable, and the app is registered with one exact redirect URI."""
```

The docstring: step 1, the provider is running, discoverable, and the app is registered with one exact redirect address.

```python
import os

import httpx
import pytest

from oidc_login.interfaces.demo_cli import Scenario
```

Imports: `os`, `httpx`, `pytest` and `Scenario`.

```python
pytestmark = pytest.mark.integration
```

The `integration` marker.

```python
def _admin_token(base: str) -> str:
    response = httpx.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.environ.get("KEYCLOAK_ADMIN", "admin"),
            "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        },
        timeout=60,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])
```

`_admin_token` signs in to Keycloak's admin interface to read the client's registration. It posts to the token endpoint of the `master` realm with `grant_type=password`, the client `admin-cli`, the admin name (default `admin`) and the admin password from the environment. `raise_for_status` turns an HTTP error into an exception, and the access token text is returned.

```python
def test_the_discovery_document_and_the_signing_keys_are_reachable(scenario: Scenario):
    step = scenario.discovery()
    assert step.passed, step.detail
    metadata = scenario.container.provider.metadata()
    assert metadata.issuer == scenario.settings.issuer
    assert metadata.revocation_endpoint.endswith("/revoke")
```

The discovery document and the signing keys are reachable; the issuer equals the configured one and the revocation endpoint ends with `/revoke`.

```python
def test_the_provider_publishes_exactly_one_rs256_signing_key(scenario: Scenario):
    keys = [key for key in scenario.container.provider.jwks()["keys"] if key.get("use") == "sig"]
    assert [key["alg"] for key in keys] == ["RS256"]
```

The provider publishes exactly one signing key and its algorithm is RS256.

```python
def test_the_app_is_registered_as_a_confidential_client_with_one_exact_redirect_uri(scenario: Scenario):
    base = scenario.settings.issuer.split("/realms/")[0]
    token = _admin_token(base)
```

The base address is cut off the issuer before `/realms/`, and an admin token is fetched.

```python
    clients = httpx.get(
        f"{base}/admin/realms/demo/clients",
        params={"clientId": scenario.settings.client_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    ).json()
    assert len(clients) == 1
    registration = clients[0]
```

The client registration is requested from the admin API with the bearer token. Exactly one client matches `notes-app`.

```python
    assert registration["redirectUris"] == [scenario.settings.redirect_uri]  # one entry, no wildcard, no second URI
    assert registration["publicClient"] is False
    assert registration["standardFlowEnabled"] is True
    assert registration["implicitFlowEnabled"] is False
    assert registration["directAccessGrantsEnabled"] is False  # no password grant: the app never sees the password
    assert registration["attributes"]["pkce.code.challenge.method"] == "S256"
    assert registration["webOrigins"] == []
```

Its registration is checked field by field: exactly one redirect address, no wildcard (`redirectUris`); a confidential client (`publicClient` is false); the code flow is enabled; the implicit flow (tokens in the address) is disabled; the direct password grant is disabled, so the app never sees the user's password; PKCE with S256 is required; and no web origins are allowed.

### Line by line: `tests/integration/test_session_lifecycle.py`

```python
"""Steps 5 and 6: the session, refresh with rotation, and sign-out with revocation."""
```

The docstring: steps 5 and 6, the session, refresh with rotation, and sign-out with revocation.

```python
import pytest

from oidc_login.interfaces.demo_cli import Scenario
```

Imports.

```python
from oidc_login.interfaces.http.security import SESSION_COOKIE
```

The session cookie name.

```python
pytestmark = pytest.mark.integration
```

The `integration` marker.

```python
@pytest.fixture
def signed_in(scenario: Scenario):
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    assert scenario.complete_login(browser, back).passed
    return scenario, browser
```

The `signed_in` fixture signs a scripted user in through the real provider and the app and returns the scenario and the browser.

```python
def test_the_session_shows_an_identity_and_no_token_and_the_server_uses_the_access_token_for_the_browser(signed_in):
    scenario, browser = signed_in
    step = scenario.session_facts(browser)
    assert step.passed, step.detail
    assert browser.cookie(SESSION_COOKIE) is not None
    assert "." not in (browser.cookie(SESSION_COOKIE) or "")  # not a JWT
```

The session shows an identity and no token, and the server uses the access token for the browser; the cookie exists and has no dot (it is not a JWT).

```python
def test_a_refresh_issues_a_new_refresh_token_and_the_old_one_is_refused_by_the_provider(signed_in):
    scenario, browser = signed_in
    step = scenario.refresh_rotation(browser)
    assert step.passed, step.detail
    assert "invalid_grant" in step.detail
```

A refresh issues a new refresh token and the real provider refuses the old one (`invalid_grant`).

```python
def test_the_session_survives_a_refresh_and_keeps_its_identity(signed_in):
    scenario, browser = signed_in
    scenario.refresh_rotation(browser)
    assert browser.get("/me").get_json()["username"] == "demo-user"
```

After a refresh the session still works and keeps its identity.

```python
def test_after_sign_out_the_old_session_and_the_old_refresh_token_are_both_refused(signed_in):
    scenario, browser = signed_in
    step = scenario.logout(browser)
    assert step.passed, step.detail
    assert scenario.container.sessions.count() == 0
```

After sign-out the old session and the old refresh token are both refused, and the store is empty.

```python
def test_a_refresh_token_the_provider_has_revoked_ends_the_session_on_the_next_use(signed_in):
    scenario, browser = signed_in
    session = scenario.server_session()
    scenario.container.provider.revoke(session.tokens.refresh_token or "")
    response = browser.post("/refresh", headers={"X-CSRF-Token": session.csrf_token})
    assert response.status_code == 401
    assert scenario.container.sessions.count() == 0
```

The refresh token is revoked directly at the provider; the next `/refresh` call gets 401 and the session is dropped.

### Line by line: `tests/integration/test_stretch_goals.py`

```python
"""Stretch goals: an elevated scope on one route, and a public client that must use PKCE."""
```

The docstring: stretch goals, an elevated scope on one route and a public client that must use PKCE.

```python
import pytest

from oidc_login.interfaces.demo_cli import Scenario

pytestmark = pytest.mark.integration
```

Imports and the marker.

```python
def test_a_route_needing_the_reports_scope_refuses_a_sign_in_that_did_not_ask_for_it(scenario: Scenario):
    step = scenario.scope_check()
    assert step.passed, step.detail
    assert "403" in step.detail
    assert "200" in step.detail
```

A route needing the `reports:read` scope refuses a sign-in that did not ask for it (403) and accepts one that did (200); the detail mentions both numbers.

```python
def test_a_public_client_cannot_exchange_a_code_without_the_pkce_verifier(scenario: Scenario):
    step = scenario.public_client_needs_pkce()
    assert step.passed, step.detail
```

A public client (no secret) cannot exchange a code without the PKCE verifier.

### Line by line: `tests/integration/test_token_validation.py`

```python
"""Step 3: the ID token Keycloak issues passes, and each kind of bad token is rejected for its own reason."""
```

The docstring: step 3, the ID token Keycloak issues passes, and each kind of bad token is rejected for its own reason.

```python
import jwt
import pytest

from oidc_login.interfaces.demo_cli import Scenario
```

Imports: PyJWT, `pytest` and `Scenario`.

```python
pytestmark = pytest.mark.integration
```

The `integration` marker.

```python
@pytest.fixture
def signed_in(scenario: Scenario) -> Scenario:
    browser = scenario.new_browser()
    _, location = scenario.start_login(browser)
    _, back = scenario.authenticate(location)
    assert scenario.complete_login(browser, back).passed
    return scenario
```

The `signed_in` fixture completes a real sign-in and returns the scenario.

```python
def test_the_real_id_token_is_signed_with_rs256_and_carries_the_claims_the_app_checks(signed_in: Scenario):
    token = signed_in.server_session().tokens.id_token
    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert header["alg"] == "RS256"
    assert header["kid"]
    assert claims["iss"] == signed_in.settings.issuer
    assert claims["aud"] == signed_in.settings.client_id
    assert claims["azp"] == signed_in.settings.client_id
    assert claims["nonce"]
    assert claims["at_hash"]
    assert claims["preferred_username"] == "demo-user"
```

The real ID token is decoded without verifying the signature (only to look at it). Its header says RS256 and has a key id; its claims have the expected issuer and audience, an authorized party equal to the client, a nonce, an `at_hash` and the username. This shows the real provider issues what the code checks.

```python
def test_wrong_audience_expired_wrong_key_none_algorithm_and_wrong_nonce_are_each_rejected_with_a_clear_reason(
    signed_in: Scenario,
):
    step = signed_in.id_token_validation()
    assert step.passed, step.detail
    for reason in ("audience claim does not match client id", "token has expired", "signature verification failed"):
        assert reason in step.detail
```

The five bad-token checks run against the real token (wrong audience, expired, wrong key, `none` algorithm, wrong nonce), and the detail contains the three most telling reasons.

### Line by line: `tests/e2e/test_server.py`

"End to end" means through the real server process, not a test client.

```python
"""A real server process, a scripted browser and Keycloak: sign-in, session, refresh, sign-out, SIGTERM."""
```

The docstring: a real server process, a scripted browser and Keycloak: sign-in, session, refresh, sign-out, SIGTERM.

```python
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
```

Imports: `os`, `re`, `signal`, `socket`, `subprocess`, `sys`, `time`, `urllib.request` and `urlsplit`.

```python
import httpx
import pytest

from oidc_login.interfaces.scripted_browser import ProviderBrowser
```

`httpx`, `pytest` and the scripted provider browser.

```python
pytestmark = pytest.mark.e2e
STARTUP_SECONDS = 180
```

The `e2e` marker, and `STARTUP_SECONDS` of 180 for a slow start.

```python
SERVE = [
    sys.executable,
    "-m",
    "gunicorn",
    "-c",
    "python:oidc_login.interfaces.gunicorn_conf",
    "oidc_login.interfaces.wsgi:build_app()",
]
```

`SERVE` is the command as a list: the current Python running gunicorn with the configuration module and the app factory.

```python
SESSION = "__Host-session"
LOGIN = "__Host-login"
```

The two cookie names.

```python
def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
```

`_free_port` binds to port 0 on the loopback address (the operating system picks a free port) and returns the number. (It is used by the refusal tests.)

```python
def _environment(port: int, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "APP_ENV": "development",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "OIDC_REDIRECT_URI": f"http://localhost:{port}/callback",
        }
    )
    env.update(extra)
    return env
```

`_environment` copies the environment and sets development mode, the loopback host, the port and a redirect address on that port; extra variables are added.

```python
def _wait_until_ready(port: int, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        assert server.poll() is None, "the server exited before it was ready"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise AssertionError(f"the server did not become ready in {STARTUP_SECONDS} seconds")
```

`_wait_until_ready` polls `/healthz` until it answers 200 or 180 seconds pass. Each loop asserts the server process has not exited (`poll()` returns `None` while it runs).

```python
@pytest.fixture
def server():
    """The app on the port its redirect URI is registered for, as production starts it (gunicorn)."""
```

The `server` fixture: the app on the port its redirect address is registered for, as production starts it.

```python
    port = urlsplit(os.environ["OIDC_REDIRECT_URI"]).port or 3000
    process = subprocess.Popen(
        SERVE,
        env=_environment(port, OIDC_REDIRECT_URI=os.environ["OIDC_REDIRECT_URI"]),
        stderr=subprocess.PIPE,
        text=True,
    )
```

The port is read from the redirect address in the environment (the realm accepts only that exact address) and gunicorn is started as a child process with standard error captured.

```python
    try:
        _wait_until_ready(port, process)
        yield port, process
```

It waits until ready and hands the port and process to the test.

```python
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=60)
```

In `finally` it sends SIGTERM and waits up to 60 seconds if the server still runs.

```python
def _cookie(response: httpx.Response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}=") and "Max-Age=0" not in header:
            return header.split("=", 1)[1].split(";", 1)[0]
    return None
```

`_cookie` returns the value of the named cookie from a response's `Set-Cookie` headers, ignoring cookies that were cleared (`Max-Age=0`).

```python
def test_the_whole_flow_against_a_running_server(server):
    port, _ = server
    app = httpx.Client(base_url=f"http://127.0.0.1:{port}", follow_redirects=False, timeout=60)
    user = ProviderBrowser("demo-user", os.environ["DEMO_USER_PASSWORD"])
```

The whole flow: an HTTP client for the app that does not follow redirects, and a scripted user at the provider.

```python
    assert app.get("/readyz").status_code == 200  # the server reaches the provider
```

`/readyz` is 200, which proves the server reaches the provider.

```python
    start = app.get("/login")
    assert start.status_code == 302
    assert "code_challenge_method=S256" in start.headers["location"]
    login_cookie = _cookie(start, LOGIN)
    assert login_cookie
```

`/login` redirects (302) with the S256 method in the address and sets the login-attempt cookie.

```python
    hop = user.authorize(start.headers["location"])
    assert hop.location is not None, f"the provider did not redirect back (status {hop.status})"
    target = urlsplit(hop.location)
    callback = app.get(f"{target.path}?{target.query}", headers={"Cookie": f"{LOGIN}={login_cookie}"})
    assert callback.status_code == 302
    session = _cookie(callback, SESSION)
    assert session
    assert "." not in session
```

The scripted user authenticates at the provider and gets redirected back; the callback is requested with the attempt cookie; it answers 302 and sets a session cookie without dots.

```python
    cookie = {"Cookie": f"{SESSION}={session}"}

    assert app.get("/me", headers=cookie).json()["username"] == "demo-user"
    assert app.get("/api/profile", headers=cookie).json()["username"] == "demo-user"
```

The session cookie is used as a header: `/me` and `/api/profile` return the demo user.

```python
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', app.get("/", headers=cookie).text)
    assert csrf
    assert app.post("/refresh", headers={**cookie, "X-CSRF-Token": csrf.group(1)}).status_code == 200
```

The CSRF token is read from the home page and `/refresh` with it answers 200.

```python
    assert app.post("/logout", headers=cookie).status_code == 403  # no CSRF token
    assert app.post("/logout", headers=cookie, data={"csrf_token": csrf.group(1)}).status_code == 303
    assert app.get("/me", headers=cookie).status_code == 401
    user.close()
    app.close()
```

A logout without the token is 403; with it, 303; then `/me` is 401. Both clients are closed.

```python
def test_sigterm_shuts_the_server_down_cleanly(server):
    _, process = server
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=60) == 0
    log = process.stderr.read()
    assert "Handling signal: term" in log
    assert "provider client closed" in log
    assert "Shutting down: Master" in log
```

SIGTERM makes the server exit with code 0; its log shows the signal handled, "provider client closed" and the master shutting down.

```python
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"OIDC_CLIENT_SECRET": ""}, "OIDC_CLIENT_SECRET is required"),
        ({"APP_ENV": "production"}, "https in production"),
        ({"OIDC_REDIRECT_URI": "http://app.example.test/callback"}, "only accepted for localhost"),
    ],
)
```

`parametrize` with three unsafe settings: an empty client secret, production mode with `http` addresses, and an `http` redirect on a non-local host. Each has the message the server must print.

```python
def test_the_server_refuses_to_start_with_an_unsafe_or_missing_setting(overrides, message):
    result = subprocess.run(
        SERVE,
        env=_environment(_free_port(), **overrides),
        capture_output=True,
        text=True,
        timeout=STARTUP_SECONDS,
        check=False,
    )
    assert result.returncode != 0
    assert message in result.stderr
```

The server is started with each; it must exit with a non-zero code and print the message on standard error. A bad configuration stops start-up.

## Try it yourself

1. Run the fast tests:
   ```bash
   make test
   ```
   Expect `151 passed` and the coverage gate printing `TOTAL ... 99%` for domain and application.
2. Count every test without running:
   ```bash
   .venv/bin/pytest --collect-only -q tests | tail -2
   ```
   Expect `178 tests collected`.
3. Run one test by name:
   ```bash
   .venv/bin/pytest tests/unit/test_pkce.py::test_the_challenge_matches_the_rfc_7636_appendix_b_example -v
   ```
   Expect one `PASSED`.
4. Break a rule and watch it fail, then revert: in `src/oidc_login/domain/claims.py` change `expected.now >= expires_at + expected.leeway` to `expected.now >= expires_at + expected.leeway + timedelta(days=1)` and run `.venv/bin/pytest tests/unit/test_claims.py -q`. Expect `3 failed`, including `test_each_failed_check_raises_its_own_error_with_a_specific_reason[...TokenExpiredError...]`. Restore with `git checkout src/oidc_login/domain/claims.py`.
5. With Keycloak up (`make up`): `make test-integration` (22 tests) and `make test-e2e` (5 tests).

## Mistakes people make

- Tests that only check the happy path. Here most tests are refusals.
- Tests that share state. Each integration test builds a fresh `Scenario` with empty stores.
- Real secrets in tests. The only credential is a local-only placeholder default for the demo user's password.
- Asserting on private details instead of behavior. The tests assert on status codes, cookies, error names and session counts.
- A server left running when a fixture fails. The e2e fixture cleans up in a `finally`.
- Timeouts too short for a loaded machine. The startup wait is 180 seconds and the scripted browser's HTTP timeout 300.

## Check yourself

1. How does pytest know a parameter is a fixture?
   *Its name matches a fixture function visible from the test.*
2. What does `pytest.raises(X, match="...")` check?
   *That exception type `X` is raised and its message matches the text.*
3. Why can the whole login flow be tested without a provider?
   *`LoginService` depends on ports, and the tests supply fakes for them.*
4. What does `--fail-under=95` do?
   *Fails the command when coverage of the chosen files drops below 95%.*
5. Why does the integration test also check `sessions.count() == 0`?
   *To prove the refusal had the consequence that matters: no session was created.*

## Further reading

- pytest 9 documentation: https://docs.pytest.org/en/stable/
- Fixtures: https://docs.pytest.org/en/stable/how-to/fixtures.html
- Parametrize: https://docs.pytest.org/en/stable/how-to/parametrize.html
- pytest-cov 7: https://pytest-cov.readthedocs.io/en/latest/
- coverage.py: https://coverage.readthedocs.io/
