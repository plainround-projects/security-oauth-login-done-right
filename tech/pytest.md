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
