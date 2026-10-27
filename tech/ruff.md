# Ruff 0.17

## What it is

Ruff is a very fast **linter** and **code formatter** for Python, written in Rust. A **linter** reads your code without running it and reports likely mistakes and style problems. A **formatter** rewrites the layout (spaces, line breaks, quotes) into one agreed style so people never argue about it. Ruff replaces several older tools at once (flake8 and its plugins, isort, pyupgrade, bandit's pattern checks, black). Pinned: `ruff==0.17.2`.

## Why this repository uses it

This is a security lesson, so the linter's **security rules** (`S`, from the bandit family) run on every `make lint`: they flag SQL built from strings, hard-coded passwords, `assert` used for checks, and unsafe subprocess calls. The other rule families keep the code consistent, so a reviewer reads logic and not formatting.

## Where it appears

| Path | What it does with ruff |
| --- | --- |
| `pyproject.toml` `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]` | All configuration. |
| `Makefile` | `lint` runs `ruff check .` and `ruff format --check .`; `format` runs `ruff check --fix .` then `ruff format .`. |
| `.github/workflows/ci.yml` | Runs `make check`, which includes both. |
| Source files | `# noqa: S101 - reason` comments where a rule is deliberately waived. |

## How it works underneath

1. Ruff parses every `.py` file into a **syntax tree** (a structured form of the code).
2. Each **rule** is a small check on that tree with a code such as `E501` or `S608`. A letter prefix is a **family** (`S` = security).
3. `ruff check` prints one finding per violation with the file, line and a pointer; it exits 1 if there is any. `--fix` applies the fixes it is sure are safe.
4. `ruff format --check` exits 1 if formatting would change anything without changing files; `ruff format` rewrites the files.
5. A trailing `# noqa: CODE` comment tells ruff "ignore this rule on this line". Good practice is to add the reason after it.

## Walkthrough of this repository's use

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src", "tests"]
```
Lines may be 120 characters. `target-version` tells ruff which Python syntax it may assume (and suggest). `src` lists the folders that hold the project's own packages, so import sorting puts `oidc_login` and `tests` in the "first-party" group rather than with third-party libraries.

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "N", "C4", "RUF", "PT", "S", "DTZ", "D100", "D101", "D103", "D104"]
```
Each entry turns on a family or a single rule:

| Code | Source | Catches |
| --- | --- | --- |
| `E`, `F` | pycodestyle, pyflakes | Syntax-level style; unused imports and variables; undefined names. |
| `I` | isort | Imports sorted and grouped. |
| `B` | bugbear | Likely bugs: mutable default arguments, `raise` without `from`. |
| `UP` | pyupgrade | Old syntax that has a newer form for Python 3.12. |
| `SIM` | simplify | Needlessly complicated code. |
| `N` | pep8-naming | Class, function and variable naming. |
| `C4` | comprehensions | Clumsy list/dict/set building. |
| `RUF` | Ruff's own | Misc, including unused `noqa` comments. |
| `PT` | pytest style | Fixture and parametrize conventions. |
| `S` | bandit | Security: `S101` assert, `S105`/`S106` hard-coded passwords, `S603`/`S607` subprocess, `S608` SQL string building, `S311` weak randomness. |
| `DTZ` | datetimez | Datetimes without a time zone. |
| `D100`, `D101`, `D103`, `D104` | pydocstyle | A docstring is required on every public module, class, function and package. |

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["D", "S101", "S105", "S106", "S603", "S607"]  # tests start this project's own server process
```
Tests need `assert` (`S101`), contain fake passwords (`S105`, `S106`), start this project's own server as a subprocess (`S603`, `S607`; the end-to-end test launches gunicorn), and do not need docstrings (`D`). These are the only blanket exceptions, and the trailing comment in the file says why.

### `noqa` and this repository

A trailing `# noqa: CODE` comment tells ruff to ignore one rule on one line, and good practice is to add the reason after the code. This repository needs **none**: `grep -rn noqa src tests` prints nothing. The security rules found nothing to waive in the application code. (The sibling repository `security-threat-model-and-harden` has a few, for `assert` used to narrow types, and one deliberate SQL-concatenation example.) `RUF100`, part of the selected `RUF` family, reports a `noqa` that no longer silences anything, so stale ones cannot accumulate.

Rules that matter for this lesson: `S105`/`S106` (hard-coded passwords: the client secret comes from the environment, never a literal in `src/`), `S113`-style missing timeouts on HTTP calls (every `httpx` call sits behind a client created with an explicit `httpx.Timeout`), `S324` (weak hashes: only SHA-256 is used), `S311` (non-cryptographic `random` for tokens: only `secrets` is used).

### Format

`ruff format` is Black-compatible: double quotes, trailing commas, wrapped calls. `ruff format --check .` in CI means a formatting difference fails the build, so contributors run `make format` first.

### What each selected rule family catches

Examples of the kind of code each family in `select` objects to (so the abbreviations mean something):

| Family | Example it flags |
| --- | --- |
| `E` (pycodestyle errors) | A line over 120 characters; a missing blank line between functions. |
| `F` (pyflakes) | `import os` that is never used; a variable used before it is defined; an f-string with no placeholders. |
| `I` (isort) | Imports not in the order standard library, third party, first party, each group alphabetical. |
| `B` (bugbear) | `def f(items=[])` (a mutable default argument shared between calls); `raise Error` inside `except` without `from`. |
| `UP` (pyupgrade) | `typing.List[int]` where `list[int]` is now right; `"%s" % x` where an f-string is clearer. |
| `SIM` (simplify) | `if x: return True else: return False` instead of `return x`. |
| `N` (pep8-naming) | A class called `my_class`; a function called `DoThing`. |
| `C4` (comprehensions) | `list([x for x in y])` or `dict([(a, b) for ...])` where a plain comprehension is enough. |
| `RUF` (ruff's own) | A `# noqa` comment that silences nothing (`RUF100`); a mutable class attribute. |
| `PT` (pytest style) | `@pytest.fixture()` with needless parentheses; a wrong type for `parametrize` names. |
| `S` (bandit rules) | `assert` used as a check (`S101`); a hard-coded password-looking string (`S105`, `S106`); a SQL string built by joining (`S608`); `subprocess` with a shell (`S602`). |
| `DTZ` (datetimez) | `datetime.now()` or `datetime.utcnow()` with no time zone. |
| `D100`, `D101`, `D103`, `D104` | A module, a class, a function or a package with no docstring. |

**The other keys.** `[tool.ruff]` has `line-length = 120`, `target-version = "py312"`, `src = ["src", "tests"]`. `[tool.ruff.lint]` has `select`. `[tool.ruff.lint.per-file-ignores]` has one line: `"tests/**" = ["D", "S101", "S105", "S106", "S603", "S607"]`. `S603` and `S607` are the subprocess rules: running a program from a variable, and running a program by partial path (`"git"`, found through `PATH`) rather than full path; the end-to-end test starts this project's own server as a subprocess. **Commands:** `ruff check .` reports problems and exits 1 if any; `ruff check --fix .` applies the safe automatic fixes; `ruff format .` rewrites the files into the formatter's layout; `ruff format --check .` only reports.

## Try it yourself

1. Lint everything:
   ```bash
   .venv/bin/ruff check .
   ```
   Expect `All checks passed!`.
2. Check formatting:
   ```bash
   .venv/bin/ruff format --check .
   ```
   Expect `55 files already formatted`.
3. Watch the SQL-injection rule fire on a throwaway file:
   ```bash
   cat > /tmp/bad.py <<'EOF'
   def q(cursor, name):
       cursor.execute("SELECT * FROM users WHERE name = '" + name + "'")
   EOF
   .venv/bin/ruff check --isolated --select S608 /tmp/bad.py
   ```
   Expect `S608 Possible SQL injection vector through string-based query construction` and `Found 1 error.` (Delete `/tmp/bad.py` afterwards.)
4. Read the explanation of any rule:
   ```bash
   .venv/bin/ruff rule S608
   ```
   Expect a page starting `# hardcoded-sql-expression (S608)`.

## Mistakes people make

- Silencing a rule project-wide because one line trips it. Use a line-level `noqa` with a reason.
- Letting `--fix` rewrite code you have not read. Review the diff.
- Running the formatter and linter with different settings on a laptop and in CI. Both read `pyproject.toml`.
- Requiring docstrings everywhere and then writing empty ones. The rules here require a docstring on public things and the code gives each a one-line purpose.

## Check yourself

1. What is the difference between `ruff check` and `ruff format`?
   *Check finds rule violations; format rewrites layout.*
2. What does `S608` catch?
   *SQL built by joining strings, a possible injection.*
3. Why do tests ignore `S101`?
   *Tests are made of `assert` statements.*
4. What is a `noqa` comment, and how many does this repository have?
   *A per-line instruction to ignore a named rule; this repository has none.*
5. Which setting makes `oidc_login` sort as first-party in imports?
   *`src = ["src", "tests"]`.*

## Further reading

- Ruff documentation: https://docs.astral.sh/ruff/
- Rules reference: https://docs.astral.sh/ruff/rules/
- Configuration: https://docs.astral.sh/ruff/configuration/
- Formatter: https://docs.astral.sh/ruff/formatter/
