# Make

## What it is

`make` is a command-line tool that reads a file called `Makefile` and runs recipes from it. A **target** is a name you ask for (`make test`). A **recipe** is the list of shell commands under it. A **prerequisite** is something the target depends on: a file that must exist and be up to date, or another target. `make` was built for compiling programs, but it works as a tidy menu of project commands.

## Why this repository uses it

Every command the lesson asks for is one short word: `make up`, `make test`, `make demo`. The same targets run on a laptop and in CI, so "it works on my machine" and "it works in CI" are the same claim.

## Where it appears

| Path | What it does with Make |
| --- | --- |
| `Makefile` | 18 documented targets, `help` included: set-up (`install`, `up`, `idp-check`), run (`run`, `demo`, `health`), quality (`lint`, `format`, `test*`, `audit`, `sbom`, `check`), containers (`docker-build`, `docker-run`, `down`); `env` and `clean` have no `##` text. |
| `.github/workflows/ci.yml` | Calls `make check`, `make audit`, `make sbom`, `make up`, `make test-integration test-e2e`, `make down`. |

The macOS version on this machine is GNU Make 3.81. The Makefile uses only features that version has.

## How it works underneath

1. `make` reads the whole `Makefile`, then looks at the target you named.
2. For a target that is a **file** (like `.venv/.installed`), it compares timestamps: if any prerequisite is newer than the target, or the target is missing, it runs the recipe. Otherwise it says nothing to do.
3. For a **phony** target (not a file, just a name), it always runs. `.PHONY:` lists those names.
4. Each recipe line starts with a **tab** (not spaces) and runs in its own `/bin/sh`. A line that fails stops `make`, unless the line starts with `-`.
5. `@` before a line hides the command echo. `$(NAME)` expands a Make variable; `$$` writes a literal `$` for the shell.

### Ideas you need first

- **A build tool.** A program that runs a list of steps in the right order, and skips steps whose results are already up to date. Programmers use it so that one short command (`make test`) replaces a long sequence they would otherwise have to remember.
- **A target, a prerequisite and a recipe.** In a `Makefile`, `name: other1 other2` followed by indented lines defines a **target** called `name`. `other1` and `other2` are its **prerequisites**: things that must be done first. The indented lines are the **recipe**: shell commands that make runs, one by one, each in its own shell.
- **A file target and a phony target.** If the target name is a real file (like `.venv/.installed`), make runs the recipe only when the file is missing or older than a prerequisite. A **phony** target (listed after `.PHONY:`) is just a name for a job and always runs.
- **A variable.** `NAME := value` stores text; `$(NAME)` uses it. `$@` means "this target's name". A doubled dollar, `$$`, passes a single `$` through to the shell.
- **Tabs.** Recipe lines must start with a Tab character, not spaces.

## Walkthrough of this repository's use

### Variables

```make
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
SERVE := $(VENV)/bin/gunicorn -c python:oidc_login.interfaces.gunicorn_conf "oidc_login.interfaces.wsgi:build_app()"
```
`?=` means "set it only if the caller has not already set it", so `make PYTHON=python3.12 install` works. `:=` assigns once, immediately. `$(shell ...)` runs a shell command while the file is read; `command -v x` prints where `x` is, and `||` tries the next one if it fails. `SERVE` is the command that starts the server, kept in a variable so `run` stays one word.

```make
-include .env
export
```
`-include` reads `.env` if it exists (the leading `-` ignores a missing file). The bare `export` passes every Make variable, including the ones from `.env`, to every recipe as environment variables. That is how `OIDC_ISSUER`, `OIDC_CLIENT_SECRET` and the rest reach the application and `idp-check` without being written in the Makefile.

### The stamp-file trick

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file
```
`.venv/.installed` is a real file whose only job is its timestamp. `touch $@` (`$@` = the target's own name) updates it after a successful install. Because it depends on the lock file and `pyproject.toml`, editing either one makes the next `make` target reinstall; otherwise nothing is reinstalled. Targets that need the environment list `$(STAMP)` as a prerequisite. The three commands: create a virtual environment (see `tech/uv-and-lock-files.md`), install exactly the locked, hash-checked packages, install this project itself in editable mode without resolving dependencies again.

### Targets with prerequisites

```make
up: env $(STAMP) ## start the identity provider (Keycloak) with the demo realm and wait until it is ready
	docker compose up -d --wait keycloak
	@$(MAKE) --no-print-directory idp-check
```
`env` (copy `.env.example` to `.env` the first time) and `$(STAMP)` (the Python environment) run first. `docker compose up -d --wait keycloak` starts only Keycloak, detached, and waits for its health check (`tech/docker-compose.md`). Then `$(MAKE) --no-print-directory idp-check` calls make again for the check; `$(MAKE)` is the right way to call make recursively.

```make
idp-check: ## step 1: the discovery document and the signing keys are reachable
	@curl -fsS $(OIDC_ISSUER)/.well-known/openid-configuration | $(PY) -c "..."
```
Explained flag by flag in `tech/curl.md`.

```make
run: env $(STAMP) ## start the app on http://localhost:3000 (needs make up)
	$(SERVE)
demo: env $(STAMP) ## run the lesson's scenario against the provider: ...
	$(PY) -m oidc_login.interfaces.demo_cli
```
`run` starts gunicorn in the foreground (Ctrl-C stops it gracefully). `demo` runs the 16-step scenario (`tech/oauth2-and-openid-connect.md`).

### `## comments` and `make help`

The text after `##` on a target line is documentation. The `help` target greps for those lines and prints them. (A bug was fixed here while these notes were written: the first version printed no target names when `.env` existed, because `.env` joined `MAKEFILE_LIST` and `grep` began prefixing file names. `grep -h` fixed it.)

### Test targets

```make
test: $(STAMP) ## unit tests with coverage (no provider needed)
	$(PY) -m pytest tests/unit --cov=oidc_login --cov-report=term
	$(PY) -m coverage report --include='src/oidc_login/domain/*,src/oidc_login/application/*' --fail-under=95

test-integration: $(STAMP) ## the provider adapter, token validation and the flow protections against Keycloak (needs make up)
	$(PY) -m pytest tests/integration -m integration -v
```
`test` runs the unit tests while measuring coverage, then fails if the domain and application folders have under 95% (`tech/pytest.md`). `test-integration` and `test-e2e` need `make up`. `test-all` lists the three as prerequisites. `check: lint test` is "everything that needs no provider", and it is what CI runs first.

### Quality and supply-chain targets

- `lint` runs four tools in sequence (`ruff check`, `ruff format --check`, `mypy`, `lint-imports`); the first failure stops it.
- `format` runs ruff with `--fix` and then `ruff format`.
- `audit` runs `pip-audit` on the lock file; `sbom` writes `sbom.cdx.json` with `cyclonedx-py` (see their notes).

### Containers and cleanup

`docker-build`, `docker-run` (`docker compose --profile app up -d --wait --build app`: starts Keycloak first, then the app) and `down` (`docker compose --profile app down -v`; `-v` also deletes the containers' volumes). `clean: down` depends on `down`, then removes the virtual environment and all tool caches with `rm -rf`.

### Every target

`$(VENV)` is `.venv`, `$(PY)` is `.venv/bin/python`, `$(STAMP)` is `.venv/.installed`; a leading `@` hides the command from make's own echo.

| Target | Prerequisites | What the recipe does |
| --- | --- | --- |
| `help` | none | Prints every `target: ... ## text` line as `target<TAB>text`, sorted. |
| `$(STAMP)` | `requirements-dev.lock`, `pyproject.toml` | Creates the virtual environment, installs the locked dev packages with hashes checked, installs the project in editable mode, then `touch`es the stamp. |
| `install` | `$(STAMP)` | Forces the stamp rule. |
| `env` | none | Copies `.env.example` to `.env` if `.env` does not exist. |
| `up` | `env`, `$(STAMP)` | `docker compose up -d --wait keycloak` (start only Keycloak, wait until healthy), then `make idp-check`. |
| `idp-check` | none | Two `curl ... \| python -c` pipelines that fetch the discovery document and the key set and print the issuer, endpoints and the number of signing keys (`tech/curl.md`). |
| `run` | `env`, `$(STAMP)` | Starts gunicorn in the foreground on port 3000 (Ctrl-C stops it gracefully). |
| `demo` | `env`, `$(STAMP)` | `python -m oidc_login.interfaces.demo_cli`: the 16-step scenario. |
| `health` | `$(STAMP)` | The `oidc-login-health` command: exit 0 when `/healthz` answers 200. |
| `lint` | `$(STAMP)` | `ruff check .`, `ruff format --check .`, `mypy`, `lint-imports`, in order. |
| `format` | `$(STAMP)` | `ruff check --fix .` then `ruff format .`. |
| `test` | `$(STAMP)` | Unit tests with coverage, then the 95% gate on domain and application. |
| `test-integration` | `$(STAMP)` | `pytest tests/integration -m integration -v` (needs Keycloak). |
| `test-e2e` | `$(STAMP)` | `pytest tests/e2e -m e2e -v` (needs Keycloak). |
| `test-all` | `test test-integration test-e2e` | The three levels in order. |
| `audit` | `$(STAMP)` | `pip-audit --no-deps --disable-pip -r requirements-dev.lock`. |
| `sbom` | `$(STAMP)` | Writes `sbom.cdx.json` with `cyclonedx-py`. |
| `check` | `lint test` | Everything that needs no provider. |
| `docker-build` | none | `docker build -t security-oauth-login-done-right:dev .` |
| `docker-run` | `env` | `docker compose --profile app up -d --wait --build app`. |
| `down` | none | `docker compose --profile app down -v`. |
| `clean` | `down` | Removes the virtual environment, logs, caches and the SBOM. |

The stamp file works as follows. `make test` needs `.venv/.installed`. If that file is missing, or `requirements-dev.lock` or `pyproject.toml` is newer, make runs: `$(PYTHON) -m venv $(VENV)` (create a **virtual environment**: a private folder with its own Python and its own installed packages, so this project's libraries never clash with another's), `pip install -q --require-hashes -r requirements-dev.lock` (install every locked package, refusing any file whose fingerprint is not in the lock), `pip install -q --no-deps -e .` (install this project itself as a link to `src/`), `touch $@` (update the stamp). If the stamp is newer than both, nothing is reinstalled.

`.PHONY:` lists the names that are jobs and not files. `-include .env` reads `.env` if it exists; the bare `export` passes every variable to every recipe, which is how `OIDC_ISSUER` reaches `idp-check`.

### Line by line: `Makefile`

Read the file as a list of **rules**: a line `target: prerequisites` followed by indented **recipe** lines (shell commands). Each recipe line starts with a tab character and runs in its own `/bin/sh`. The `##` text after a target is a comment that `make help` prints.

```make
# make up | run | demo | test | test-integration | test-e2e | lint | audit | sbom | down      (make help lists everything)
```

A comment listing the main targets.

```make
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
```

`PYTHON ?= ...` sets the variable only if it is not already set. `$(shell ...)` runs a command and uses its output; `command -v` prints the path of a program if it exists and `||` tries the next one if not. So Python 3.13 is used if present, else 3.12, else any `python3`.

```make
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
```

`:=` assigns once, at this line. `VENV` is the folder of the **virtual environment** (a private folder with its own Python and installed packages). `PY` is the Python inside it. `STAMP` is an empty marker file recording that the install is done.

```make
SERVE := $(VENV)/bin/gunicorn -c python:oidc_login.interfaces.gunicorn_conf "oidc_login.interfaces.wsgi:build_app()"
```

`SERVE` is the gunicorn command line used by the `run` target.

```make
-include .env
export
```

`-include .env` reads `.env` as more make variables if it exists (the `-` means no error if it is missing); a bare `export` passes every make variable to the recipes as environment variables. That is how `OIDC_ISSUER` reaches the `idp-check` target.

```make
.PHONY: help install env up idp-check run demo health lint format test test-integration test-e2e test-all audit sbom \
        check docker-build docker-run down clean
```

`.PHONY` lists targets that are names, not files, so a file called `test` cannot make `make test` do nothing. The backslash continues the line.

```make
help: ## list the targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort
```

`help` runs `grep` to select lines like `name: ... ## text` from all makefiles (`-h` hides file names, `-E` enables extended patterns), `sed` to turn `: ... ## ` into a tab, and `sort`. `@` hides the command itself.

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@
```

The stamp rule depends on the lock file and `pyproject.toml`. It creates the virtual environment, installs the development lock with `--require-hashes` (pip refuses a package whose hash is not listed), installs the project itself with `--no-deps -e .` (an **editable** install that uses `src/` directly) and creates the stamp (`$@` is the target's name).

```make
install: $(STAMP) ## create .venv from the lock file
```

`install` depends on the stamp.

```make
env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
```

`env` copies `.env.example` to `.env` if `.env` does not exist.

```make
# Start Keycloak and wait until the demo realm is imported and the provider answers.
up: env $(STAMP) ## start the identity provider (Keycloak) with the demo realm and wait until it is ready
	docker compose up -d --wait keycloak
	@$(MAKE) --no-print-directory idp-check
```

`up` needs `env` and the stamp. `docker compose up -d --wait keycloak` starts Keycloak in the background and waits for its health check; then `$(MAKE) --no-print-directory idp-check` runs the next target. The leading `@` hides the command.

```make
idp-check: ## step 1: the discovery document and the signing keys are reachable
	@curl -fsS $(OIDC_ISSUER)/.well-known/openid-configuration | $(PY) -c "import json,sys; d=json.load(sys.stdin); print('issuer                ', d['issuer']); print('authorization_endpoint', d['authorization_endpoint']); print('jwks_uri              ', d['jwks_uri'])"
	@curl -fsS $(OIDC_ISSUER)/protocol/openid-connect/certs | $(PY) -c "import json,sys; print('signing keys          ', len(json.load(sys.stdin)['keys']))"
```

`idp-check` uses `curl` (`tech/curl.md`) with `-f` (fail on an HTTP error status), `-s` (silent) and `-S` (but show errors) to fetch the discovery document and then the signing keys, and pipes each into a short Python program (`python -c "..."`) that parses the JSON and prints the issuer, the authorization endpoint, the keys address and the number of signing keys. The `|` pipe sends one program's output to the next program's input.

```make
# Foreground server: gunicorn on APP_HOST:APP_PORT, SIGTERM or Ctrl-C shuts it down gracefully.
run: env $(STAMP) ## start the app on http://localhost:3000 (needs make up)
	$(SERVE)
```

`run` starts the app in the foreground; SIGTERM or Ctrl-C shuts it down gracefully.

```make
demo: env $(STAMP) ## run the lesson's scenario against the provider: sign-in, each protection, refresh, logout (needs make up)
	$(PY) -m oidc_login.interfaces.demo_cli
```

`demo` runs the scenario: `python -m oidc_login.interfaces.demo_cli` (`-m` runs a module).

```make
health: $(STAMP) ## exit 0 when the running app answers /healthz
	$(VENV)/bin/oidc-login-health
```

`health` runs the health program.

```make
lint: $(STAMP) ## ruff check (with security rules), ruff format check, mypy, import-linter
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports
```

`lint` runs four checks, stopping at the first failure: `ruff check .`, `ruff format --check .`, `mypy` and `lint-imports`.

```make
format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .
```

`format` applies ruff's safe fixes and formatting.

```make
# Unit tests need no provider. The domain and application must stay at 95% coverage or more.
test: $(STAMP) ## unit tests with coverage (no provider needed)
	$(PY) -m pytest tests/unit --cov=oidc_login --cov-report=term
	$(PY) -m coverage report --include='src/oidc_login/domain/*,src/oidc_login/application/*' --fail-under=95
```

`test` runs the unit tests with coverage, then `coverage report` for the domain and application folders with `--fail-under=95`: it fails if less than 95 percent of those lines ran.

```make
test-integration: $(STAMP) ## the provider adapter, token validation and the flow protections against Keycloak (needs make up)
	$(PY) -m pytest tests/integration -m integration -v
```

`test-integration` runs the tests marked `integration` against Keycloak, verbosely.

```make
test-e2e: $(STAMP) ## a real server process, a scripted browser and Keycloak (needs make up)
	$(PY) -m pytest tests/e2e -m e2e -v
```

`test-e2e` runs the tests marked `e2e`: a real server process, a scripted browser and Keycloak.

```make
test-all: test test-integration test-e2e ## every test level (needs make up)
```

`test-all` is a list of other targets.

```make
audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock
```

`audit` runs `pip-audit` on the lock (`--no-deps` stops it resolving more packages, `--disable-pip` stops it building a temporary environment).

```make
sbom: $(STAMP) ## write sbom.cdx.json (CycloneDX) for the locked runtime dependencies
	$(VENV)/bin/cyclonedx-py requirements requirements.lock --of JSON -o sbom.cdx.json
	@echo "wrote sbom.cdx.json"
```

`sbom` writes a CycloneDX bill of materials of the runtime lock file and prints a line.

```make
check: lint test ## everything that needs no provider
```

`check` runs `lint` and `test`.

```make
docker-build: ## build the container image
	docker build -t security-oauth-login-done-right:dev .
```

`docker-build` builds the image and tags it.

```make
docker-run: env ## run the image next to Keycloak and wait until it is healthy
	docker compose --profile app up -d --wait --build app
```

`docker-run` starts the `app` service (in the compose profile `app`), building it first and waiting for its health.

```make
down: ## stop the containers and delete their data
	docker compose --profile app down -v
```

`down` stops the containers and deletes their data (`-v`).

```make
clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage sbom.cdx.json
```

`clean` removes the environment, logs, caches and the SBOM.

## Try it yourself

1. List every target with its description:
   ```bash
   make help
   ```
   Expect 18 lines such as `audit	check the locked dependencies for known vulnerabilities`.
2. See what a target would run without running it:
   ```bash
   make -n test
   ```
   Expect the two `python -m pytest` and `python -m coverage` lines printed, not executed.
3. Check the stamp-file idea:
   ```bash
   make install && make install
   ```
   Expect the second call to print `make: Nothing to be done for `install'.` (the quote characters differ between make versions).
4. Force a reinstall:
   ```bash
   touch pyproject.toml && make -n install
   ```
   Expect the `venv` and `pip install` lines to appear again.

## Mistakes people make

- Spaces instead of a tab at the start of a recipe line. The `.editorconfig` sets `indent_style = tab` for `Makefile`.
- Using `$VAR` where Make needs `$(VAR)`, or `$VAR` where the shell needs `$$VAR`.
- Forgetting `.PHONY`: if a file named `test` ever existed, `make test` would say "up to date". Every non-file target is listed.
- Each recipe line is a separate shell, so `cd dir` on one line does not affect the next. This Makefile never relies on that.
- Hiding failures with a leading `-` on a recipe line or with `|| true`. The Makefile never uses a leading `-` on a recipe line and has no `|| true`.

## Check yourself

1. What does `?=` mean?
   *Assign only if the variable has no value yet.*
2. Why does `.venv/.installed` exist?
   *Its timestamp tells make whether the lock file or `pyproject.toml` changed since the last install.*
3. What does `$$` do in a recipe?
   *It passes a literal `$` to the shell.*
4. Why does `up` call `$(MAKE) --no-print-directory idp-check` instead of just `make idp-check`?
   *`$(MAKE)` is make's own recursive call; it passes flags and the jobserver correctly.*
5. What happens if one line of a recipe fails?
   *make stops and reports an error, unless the line begins with `-`.*

## Further reading

- GNU Make manual (version 3.81 on macOS; the manual for 4.x is a superset): https://www.gnu.org/software/make/manual/make.html
- Phony targets: https://www.gnu.org/software/make/manual/make.html#Phony-Targets
