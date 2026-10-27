# pyproject.toml packaging and setuptools 75

## What it is

**Packaging** is turning a folder of Python files into something `pip` can install: it needs a name, a version, a list of dependencies, which files to include and which commands to create. In modern Python all of that is declared in `pyproject.toml` (format: `tech/toml.md`). **setuptools** is the long-standing **build backend**: the program that reads that metadata and builds the installable thing (a **wheel**, a zip file with a `.whl` name). The `[build-system]` table names the backend; `pip` downloads it, runs it, then installs the wheel. `setuptools>=75` is the requirement; the Docker image's own copy is removed after the install.

## Why this repository uses it

The code lives under `src/oidc_login/` (the "src layout"). Installing the project (`pip install -e .` locally, `pip install --no-deps .` in Docker) is what makes `import oidc_login` work from anywhere and what creates the two commands `oidc-login-health` and `oidc-login-demo`. The src layout also stops tests from accidentally importing the working copy instead of the installed one.

## Where it appears

| Path | What it does |
| --- | --- |
| `pyproject.toml` `[build-system]`, `[project]`, `[project.scripts]`, `[tool.setuptools.*]` | Metadata, commands, package discovery, bundled files. |
| `Makefile` | `pip install --no-deps -e .` in the stamp rule. |
| `Dockerfile` | `COPY pyproject.toml README.md ./`, `COPY src ./src`, `RUN pip install --no-deps .`. |
| `src/security_oauth_login_done_right.egg-info/` | Generated metadata folder left by an editable install; ignored by git (`*.egg-info/`). |

## How it works underneath

1. `pip install .` reads `[build-system]`, creates a temporary isolated environment, installs `setuptools>=75` there, and asks it to build a wheel from the project folder.
2. setuptools reads `[project]` for the metadata, finds the packages to include, and writes the wheel.
3. pip unpacks the wheel into the environment's `site-packages` and writes small launcher programs for `[project.scripts]` into `.venv/bin/`.
4. An **editable** install (`-e`) instead drops a link, so Python imports straight from `src/`; edits apply at once.

## Walkthrough of this repository's use

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```
`requires` is what the build needs. `build-backend` is the Python object pip calls.

```toml
[project]
name = "security-oauth-login-done-right"
version = "0.1.0"
description = "..."
readme = "README.md"
requires-python = ">=3.12"
```
Name, version, a one-line description, the README shown on a package page, and the oldest Python allowed. Installing on 3.11 fails with a clear message. That is why the `Dockerfile` copies `README.md`: the build reads it.

```toml
[tool.setuptools.packages.find]
where = ["src"]
```
Look for packages (folders with `__init__.py`) under `src/` only. Without this, setuptools might include `tests/` or `scripts/`.

```toml
[tool.setuptools.package-data]
"oidc_login.interfaces.http" = ["templates/*.html", "static/*.css"]
```
By default only `.py` files are packaged. The HTML templates and the stylesheet are not Python, so this line names them. Without it the container would start and then fail with "TemplateNotFound" on the first page. (The health endpoints do not render templates, so only a test that loads the home page or an error page would notice: the unit tests of the HTTP layer do.)

```toml
[project.scripts]
oidc-login-health = "oidc_login.interfaces.health_cli:main"
oidc-login-demo = "oidc_login.interfaces.demo_cli:main"
```
Creates two commands. `module:function` is what the launcher calls; the function's return value becomes the exit code.

### Order in the Dockerfile and why `--no-deps`

The dependencies are installed first from the hashed lock; the project is installed second with `--no-deps`, so pip cannot reach out to resolve anything or pull an unreviewed package.

## Try it yourself

1. See the installed commands:
   ```bash
   ls .venv/bin | grep oidc
   ```
   Expect `oidc-login-demo` and `oidc-login-health`.
2. See the metadata pip recorded:
   ```bash
   .venv/bin/pip show security-oauth-login-done-right
   ```
   Expect `Name: security-oauth-login-done-right`, `Version: 0.1.0`, `Requires: flask, gunicorn, httpx, PyJWT`, and an `Editable project location`.
3. Confirm the templates are packaged (a wheel build; needs network the first time because of build isolation):
   ```bash
   .venv/bin/pip wheel --no-deps -w /tmp/whl . -q && unzip -l /tmp/whl/*.whl | grep -E "templates|static"; rm -rf /tmp/whl
   ```
   Expect the three `templates/*.html` files (`base`, `error`, `home`) and `static/style.css` in the listing.
4. Ask where Python imports the package from:
   ```bash
   .venv/bin/python -c "import oidc_login; print(oidc_login.__file__)"
   ```
   Expect a path ending `src/oidc_login/__init__.py`.

## Mistakes people make

- Forgetting `package-data`: templates missing from the built package.
- Importing from the repository root because the working directory is on the path, so tests pass while the installed package is broken. The src layout and the Docker build catch it.
- Mixing `setup.py`, `setup.cfg` and `pyproject.toml`. This project uses only the last.
- Pinning the project's own dependencies exactly in `pyproject.toml`. Ranges go there; exact versions go in the lock files (`tech/uv-and-lock-files.md`).
- Committing `*.egg-info/` or `build/`. Both are in `.gitignore`.

## Check yourself

1. What is a wheel?
   *A built, ready-to-unpack package file (`.whl`).*
2. What does the `src` layout protect against?
   *Accidentally importing the source folder instead of the installed package.*
3. Why list the templates in `package-data`?
   *Only `.py` files are packaged by default.*
4. What does `[project.scripts]` create?
   *Commands in `.venv/bin` that call a Python function and use its return value as the exit code.*
5. Why is the project installed with `--no-deps` in Docker?
   *Its dependencies came from the hashed lock; nothing else should be resolved.*

## Further reading

- Python Packaging User Guide: https://packaging.python.org/en/latest/
- `pyproject.toml` specification: https://packaging.python.org/en/latest/specifications/pyproject-toml/
- setuptools documentation: https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html
- Src layout vs flat layout: https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
