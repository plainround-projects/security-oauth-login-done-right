# TOML (the format of `pyproject.toml`)

## What it is

TOML ("Tom's Obvious Minimal Language") is a plain-text file format for configuration. It stores named values in a way that is easy for people to read and for programs to parse. Python 3.11 and later can read it with the built-in `tomllib` module. This repository has one TOML file, `pyproject.toml`; nearly every Python tool in the project (setuptools, ruff, mypy, pytest, coverage, import-linter) reads its settings from it.

## Why this repository uses it

One file for project metadata, dependencies and all tool settings keeps the configuration in one reviewable place, and a tool configured in `pyproject.toml` behaves the same for every contributor and in CI.

## Where it appears

| Path | What it does |
| --- | --- |
| `pyproject.toml` | The only TOML file; about 100 lines. |

## How it works underneath

A TOML file is a set of **key = value** pairs, grouped into **tables** whose names are in square brackets.

- A **string** is in double quotes: `name = "security-oauth-login-done-right"`.
- A **number** is bare: `line-length = 120`. A **boolean** is `true` or `false`.
- An **array** is in square brackets, items separated by commas, and may span lines: `layers = ["a", "b"]`.
- An **inline table** is a small table in braces: `license = { text = "MIT" }`.
- A **table** header `[tool.ruff]` starts a section. The dot means nesting: key `ruff` inside `tool`.
- A double-bracket header `[[tool.importlinter.contracts]]` is an **array of tables**: each occurrence adds one more item to the list `contracts`.
- `#` starts a comment.

`tomllib.load(file)` returns ordinary Python dictionaries and lists, so a tool just reads `data["tool"]["ruff"]["line-length"]`.

## Walkthrough of this repository's use

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```
Standard table that tells installers how to build the project (see `tech/pyproject-and-setuptools.md`).

```toml
[project]
name = "security-oauth-login-done-right"
version = "0.1.0"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Sumit Srivastava" }]
dependencies = [
    "flask>=3.1,<4",
    "gunicorn>=23,<26",
    "httpx>=0.27,<1",
    "PyJWT[crypto]>=2.9,<3",
]
```
`authors` is an array containing one inline table. `dependencies` is a multi-line array of strings in the format used for Python requirements: a name, then version bounds. `>=3.1,<4` means "3.1 or newer but below 4". `PyJWT[crypto]` asks for the library plus its optional **extra** named `crypto`, which pulls in the `cryptography` package needed for RSA signatures.

```toml
[project.optional-dependencies]
dev = [ "pytest>=8,<10", ... ]
```
Table `project`, sub-table `optional-dependencies`, key `dev`: a named group of extra packages (pytest, ruff, mypy and the other tools), installed only when asked for (`pip install .[dev]` or `uv pip compile --extra dev`).

```toml
[project.scripts]
oidc-login-health = "oidc_login.interfaces.health_cli:main"
```
Key = command name, value = `module:function`. Keys with hyphens are fine bare.

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["D", "S101", "S105", "S106", "S603", "S607"]
```
A key that contains characters other than letters, digits, `-` and `_` (here `/` and `*`) must be quoted.

```toml
[[tool.importlinter.contracts]]
name = "Layers: ..."
type = "layers"
...
[[tool.importlinter.contracts]]
name = "Domain and application know nothing about ..."
type = "forbidden"
```
Two `[[...]]` blocks give a list with two contracts.

```toml
[tool.pytest.ini_options]
markers = [
    "integration: needs the identity provider from docker-compose.yml (make up)",
```
An array of strings, one per line, with a trailing comma allowed.

Each tool owns its own `[tool.<name>]` table: `ruff` (`tech/ruff.md`), `mypy` (`tech/mypy.md`), `pytest` and `coverage` (`tech/pytest.md`), `importlinter` (`tech/import-linter.md`), `setuptools` (`tech/pyproject-and-setuptools.md`).

### Every tool table in `pyproject.toml`

- `[tool.ruff]`: `line-length` (longest allowed line), `target-version` (the Python version to assume), `src` (folders holding the project's own packages). `[tool.ruff.lint]`: `select` (the rules to run). `[tool.ruff.lint.per-file-ignores]`: a table from a file pattern to the rules waived there.
- `[tool.mypy]`: `python_version`, `strict`, `files`. `[[tool.mypy.overrides]]`: a list of exceptions, each with `module` (patterns) and the flags to relax.
- `[tool.pytest.ini_options]`: `testpaths` (where to look), `addopts` (flags always added: `-ra` prints a summary of every non-passing test, `--strict-markers` makes an unregistered marker an error), `markers` (a list of `name: description` strings for the two labels `integration` and `e2e`).
- `[tool.coverage.run]`: `source = ["oidc_login"]` (measure this package) and `branch = true` (also count each side of every `if`). `[tool.coverage.report]`: `show_missing = true` (print the line numbers not run) and `skip_covered = false` (still list fully covered files).
- `[tool.importlinter]`: `root_package` (the package to analyze) and `include_external_packages = true` (also track third-party imports). `[[tool.importlinter.contracts]]` appears twice: a `layers` contract with `layers = [...]` from highest to lowest, and a `forbidden` contract with `source_modules` and `forbidden_modules`.
- `[tool.setuptools.packages.find]` and `[tool.setuptools.package-data]`, as in `tech/pyproject-and-setuptools.md`.

The whole file in one sentence per top-level table: `[build-system]` how to build, `[project]` what this is, `[project.optional-dependencies]` the dev tools, `[project.scripts]` the two commands, then one `[tool.*]` table per tool that reads it.

## Try it yourself

1. Parse the file with the standard library:
   ```bash
   .venv/bin/python -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb')); print(d['project']['name']); print(list(d['tool']))"
   ```
   Expect `security-oauth-login-done-right` and `['setuptools', 'ruff', 'mypy', 'pytest', 'coverage', 'importlinter']`.
2. Read one array of tables:
   ```bash
   .venv/bin/python -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb')); print([c['type'] for c in d['tool']['importlinter']['contracts']])"
   ```
   Expect `['layers', 'forbidden']`.
3. See the dependency list as Python sees it:
   ```bash
   .venv/bin/python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies'])"
   ```
   Expect four strings: `flask>=3.1,<4`, `gunicorn>=23,<26`, `httpx>=0.27,<1`, `PyJWT[crypto]>=2.9,<3`.
4. Break the syntax on a copy and see the error:
   ```bash
   printf 'name = "x\n' > /tmp/bad.toml
   .venv/bin/python -c "import tomllib; tomllib.load(open('/tmp/bad.toml','rb'))"
   ```
   Expect `tomllib.TOMLDecodeError`. (Delete `/tmp/bad.toml`.)

## Mistakes people make

- Forgetting quotes around a string value, or using single quotes where an escape is needed.
- Writing `[tool.ruff.lint]` twice, which is an error: a table may be defined once.
- Confusing `[x]` with `[[x]]`: one table versus a list item.
- Expecting indentation to matter. In TOML it does not (unlike YAML); it is only for readability.
- Putting version ranges in a way pip cannot read. Requirement strings are standard Python ones.

## Check yourself

1. How do you write a nested table `ruff` inside `tool`?
   *The header `[tool.ruff]`.*
2. What does `[[tool.importlinter.contracts]]` mean?
   *One more item in the array of tables `contracts`.*
3. Why must `"tests/**"` be quoted?
   *Because it contains characters not allowed in a bare key.*
4. Which module reads TOML in the standard library?
   *`tomllib`, in Python 3.11 and later.*
5. What does `>=3.1,<4` allow?
   *Any version from 3.1 up to, but not including, 4.*

## Further reading

- TOML specification (v1.0.0): https://toml.io/en/v1.0.0
- `tomllib`: https://docs.python.org/3.12/library/tomllib.html
- Writing `pyproject.toml`: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
