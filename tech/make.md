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
