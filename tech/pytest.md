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
