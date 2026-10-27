# pip-audit 2.10

## What it is

pip-audit is a command-line tool that checks the Python packages you depend on against a database of **known vulnerabilities**. A known vulnerability has an ID such as `PYSEC-2024-123` or `GHSA-xxxx-xxxx-xxxx` (a "CVE"-style advisory) and a list of affected versions. pip-audit takes your list of exact package versions, asks the Python Packaging Advisory Database (served by PyPI's API) which have advisories, and prints them with the fixed version. Pinned: `pip-audit==2.10.1`.

## Why this repository uses it

A secure application on top of a vulnerable library is not secure. The lesson asks for dependencies to be pinned and checked, and for the check to run on every change. `make audit` is that check, and CI runs it.

## Where it appears

| Path | What it does |
| --- | --- |
| `Makefile` target `audit` | `$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock` |
| `.github/workflows/ci.yml` | `- run: make audit` in job `check`. |
| `requirements-dev.lock`, `requirements.lock` | The pinned input. |

## How it works underneath

1. pip-audit reads a requirements file where every line is `name==version`.
2. For each pair it queries the vulnerability service over HTTPS (so it **needs network access**).
3. It prints a table of any vulnerable package, its version, the advisory ID and the version that fixes it, and exits 1. With none, it prints `No known vulnerabilities found` and exits 0.
4. Without `--no-deps` it would ask `pip` to resolve dependencies first, which creates a temporary environment. With a fully pinned, hash-checked file that step is unnecessary.

## Walkthrough of this repository's use

```make
audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock
```
- `-r requirements-dev.lock` audit exactly this file: the locked runtime *and* development dependencies, 80 pinned lines.
- `--no-deps` do no dependency resolution; require every requirement to be pinned to an exact version. The lock file is already the full resolved set, so what is audited is what is installed.
- `--disable-pip` do not use `pip` at all for resolution. The help text says this is allowed only with hashed requirements files or with `--no-deps`; the lock file has both. It makes the run faster and removes a moving part.

The lock file is made by `uv pip compile ... --generate-hashes` (see `tech/uv-and-lock-files.md`), so audit, install and the container build all use the identical list. `Dockerfile` installs `requirements.lock` with `--require-hashes`.

What happens when it finds something: the target fails, CI turns red, and a person decides: upgrade the pin (edit `pyproject.toml` bounds if needed, recompile the lock), or, if the advisory does not apply, ignore it with `--ignore-vuln ID` and a written reason. This repository has no ignores.

## Try it yourself

1. Run it (needs internet):
   ```bash
   make audit
   ```
   Expect `No known vulnerabilities found` and exit code 0.
2. Read the options:
   ```bash
   .venv/bin/pip-audit --help | head -30
   ```
   Expect to see `--no-deps`, `--disable-pip`, `-r`, `--ignore-vuln` and `-o`.
3. Make it fail on a scratch file (do not touch the lock):
   ```bash
   printf 'pyyaml==5.3.1\n' > /tmp/old.txt
   .venv/bin/pip-audit --no-deps --disable-pip -r /tmp/old.txt
   ```
   Expect `Found 2 known vulnerabilities in 1 package` and a table with `pyyaml 5.3.1 PYSEC-2021-142 5.4` (the fixed version is 5.4), and exit code 1 (two warnings about hashing appear first because this scratch file has no hashes). (Delete `/tmp/old.txt`. This needs network access; if you are offline the command fails with a connection error instead, which is not the same as "no vulnerabilities".)
4. See the exit code:
   ```bash
   make audit; echo "exit $?"
   ```

## Mistakes people make

- Auditing only what you wrote in `pyproject.toml` and not the transitive packages. The lock file has them all.
- Ignoring advisories without a reason or an expiry date.
- Running the audit only once. New advisories appear daily, so CI runs it on every push (a scheduled run is the next step; the pipeline-security lesson in this series adds a weekly rescan).
- Treating "no network, no output" as a pass. A failed lookup is an error here, not a clean result.
- Auditing a loose `>=` range: the result then depends on what happens to be installed.

## Check yourself

1. What does pip-audit send to the vulnerability service?
   *Package names and exact versions.*
2. Why `--no-deps`?
   *The lock file already lists every dependency pinned, so no resolution is needed.*
3. Why does pip-audit need the network?
   *The advisory database is queried online.*
4. What should you do when it reports a vulnerable pin?
   *Upgrade the dependency and recompile the lock; ignore only with a written reason.*
5. Which files are audited?
   *`requirements-dev.lock`, which includes the runtime set.*

## Further reading

- pip-audit on PyPI and GitHub: https://pypi.org/project/pip-audit/ and https://github.com/pypa/pip-audit
- Python Packaging Advisory Database: https://github.com/pypa/advisory-database
- OSV (the data format behind many advisories): https://osv.dev/
