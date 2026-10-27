# import-linter 2.15

## What it is

import-linter is a Python command-line tool that checks the **imports** between your own modules against rules you write down. Normal linters check single lines. This one checks the *architecture*: "code in folder A must never import code in folder B". You declare rules, called **contracts**, in `pyproject.toml`; the command is `lint-imports`. It builds a graph of who imports whom (using a library called `grimp`) and fails if a contract is **broken**. Pinned: `import-linter==2.15`.

## Why this repository uses it

The design in the lesson is layered: `domain` (pure rules), `application` (use cases), `infrastructure` (the provider client, the JWT verifier, in-memory stores, settings, logging), `interfaces` (HTTP). The security argument depends on it: the token checks live in `domain` and `application`, so they cannot be bypassed or contaminated by Flask or HTTP-client code, and they can be tested without an identity provider. A rule on paper erodes; a rule in the build does not.

## Where it appears

| Path | What it does |
| --- | --- |
| `pyproject.toml` `[tool.importlinter]` and two `[[tool.importlinter.contracts]]` blocks | The rules. |
| `Makefile` (`lint`) | Runs `.venv/bin/lint-imports`. |
| `.gitignore`, `.dockerignore` | Ignore the `.import_linter_cache` folder. |

## How it works underneath

1. `lint-imports` reads the configuration, imports nothing of your code, and instead reads the source files to find `import` statements (static analysis).
2. It builds a graph: a node per module, an arrow per import. With `include_external_packages = true` it also records imports of third-party packages such as `flask`.
3. For each contract it asks the graph: "is there any path from X to Y?". A path can go through several modules, so an indirect import also counts.
4. It prints each contract as KEPT or BROKEN, with the import chain that breaks it, and exits 1 if any is broken.

## Walkthrough of this repository's use

```toml
[tool.importlinter]
root_package = "oidc_login"
include_external_packages = true
```
Analyse the package `oidc_login`, and include third-party packages in the graph so contract 2 can name them.

```toml
[[tool.importlinter.contracts]]
name = "Layers: interfaces -> infrastructure -> application -> domain, never upward"
type = "layers"
layers = [
    "oidc_login.interfaces",
    "oidc_login.infrastructure",
    "oidc_login.application",
    "oidc_login.domain",
]
```
A **layers** contract lists packages from highest to lowest. A higher layer may import a lower one; a lower layer must never import a higher one. So `domain` cannot import `application`, `application` cannot import `infrastructure`, and nothing imports `interfaces`. This is the "dependencies point inward" rule of ports-and-adapters design: the infrastructure *implements* ports defined in the application layer, and `interfaces/composition.py` is the one place that connects them.

```toml
[[tool.importlinter.contracts]]
name = "Domain and application know nothing about Flask, httpx or the JWT library"
type = "forbidden"
source_modules = ["oidc_login.domain", "oidc_login.application"]
forbidden_modules = ["flask", "werkzeug", "jinja2", "httpx", "jwt", "cryptography"]
```
A **forbidden** contract says: nothing in `source_modules` may import (directly or through any chain) anything in `forbidden_modules`. This is what keeps the security-relevant rules independent of the web framework, the database driver and the hashing library. It is also why the tests of those layers need no database.

### What a violation looks like

If someone writes `import flask` in `domain/claims.py`, the second contract reports it with the chain, for example `oidc_login.domain.claims -> flask`, and the build fails at `make lint`, before review.

## Try it yourself

1. Run it:
   ```bash
   .venv/bin/lint-imports
   ```
   Expect `Analyzed 52 files, 145 dependencies.`, both contracts `KEPT`, and `Contracts: 2 kept, 0 broken.`
2. Break the first contract on purpose (then revert): add `from oidc_login.infrastructure import clock` to `src/oidc_login/domain/models.py` and run `.venv/bin/lint-imports`. Expect `Broken contracts`, the layers contract named, and the lines `oidc_login.domain is not allowed to import oidc_login.infrastructure:` and `oidc_login.domain.models -> oidc_login.infrastructure.clock`. Undo: `git checkout src/oidc_login/domain/models.py`.
3. Break the second one (then revert): add `import flask` to `src/oidc_login/application/ports.py`. Expect the forbidden contract to be `BROKEN`, with `oidc_login.application is not allowed to import flask:` and `oidc_login.application.ports -> flask`. Undo with `git checkout`.
4. Run a single contract:
   ```bash
   .venv/bin/lint-imports --help
   ```
   Expect the option `--contract` for limiting the check, and `--no-cache` to bypass the cache.

## Mistakes people make

- Writing the layering only in a README. This repository enforces it.
- Forgetting indirect imports. Both contract types follow chains.
- Forgetting `include_external_packages = true`, which makes a forbidden contract on third-party names silently check nothing.
- Allowing "just one" exception, which becomes the pattern.
- Putting the wiring code in a lower layer. Wiring is in `interfaces/composition.py` on purpose, the one place allowed to know both sides.

## Check yourself

1. What is a contract?
   *A rule in `pyproject.toml` about which modules may import which.*
2. In a layers contract, which direction may imports go?
   *From a higher layer to a lower one; never upward.*
3. Why must `domain` not import `flask`?
   *The security rules stay independent of the web framework and testable without it.*
4. Does the forbidden contract catch an import through an intermediate module?
   *Yes; it checks for any chain.*
5. What does `include_external_packages = true` add?
   *Third-party packages as nodes in the graph so contracts can name them.*

## Further reading

- import-linter documentation: https://import-linter.readthedocs.io/en/stable/
- Contract types: https://import-linter.readthedocs.io/en/stable/contract_types.html
- Ports and adapters (hexagonal architecture), Alistair Cockburn: https://alistair.cockburn.us/hexagonal-architecture/
