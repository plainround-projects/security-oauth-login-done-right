# GitHub Actions

## What it is

GitHub Actions is GitHub's built-in **automation service** (continuous integration, or **CI**). You put a workflow file in `.github/workflows/`, and every time something happens in the repository (a push, a pull request), GitHub starts a fresh virtual machine, checks out your code, and runs the steps you listed. If a step fails, the run is marked failed and shows a red mark next to the commit.

Terms: a **workflow** is one YAML file (`tech/yaml.md`). It has **jobs**; each job runs on its own **runner** (a machine). A job is a list of **steps**. A step is either a shell command (`run:`) or a reusable **action** (`uses:`), a packaged step written by someone else.

## Why this repository uses it

"It works on my machine" is not evidence. The lesson wants every control proven by something other than the author's laptop, so the same `make` targets run in a clean environment on every push. CI also runs the supply-chain checks (dependency audit, SBOM) every time.

## Where it appears

| Path | What it does |
| --- | --- |
| `.github/workflows/ci.yml` | The only workflow: two jobs, `check` and `provider` (40 lines). |

## How it works underneath

1. `on: [push, pull_request]` registers the workflow for those events.
2. GitHub allocates a runner (`ubuntu-latest`: a fresh Linux VM with Docker, Python and common tools), gives it a short-lived token with the permissions the workflow requests, and runs the steps in order.
3. The two jobs run **in parallel** on two separate machines (no `needs:` links them).
4. When all steps succeed the job passes. Any non-zero exit code fails the step and, by default, skips the rest of the job.
5. The VM is destroyed afterwards, so nothing persists except uploaded **artifacts**.

## Walkthrough of this repository's use

```yaml
name: ci

on: [push, pull_request]

permissions:
  contents: read
```
`permissions` limits what the job's automatic token can do. `contents: read` means read the repository, and nothing else (no write, no issues, no packages). Least privilege: a compromised step cannot push code.

### Job `check`

```yaml
check:
  name: Format, lint (with security rules), types, import rules, unit tests with coverage, dependency audit, SBOM
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      with:
        persist-credentials: false
```
`actions/checkout` copies the repository onto the runner. The long hex string is a **full commit SHA**; the trailing comment records the human-readable version. Pinning to a SHA, not a tag like `@v7`, matters: tags can be moved, so a compromised action could be re-published under the same tag; a commit SHA cannot be changed. `persist-credentials: false` stops checkout from leaving the token in the local git configuration where later steps could read it.

```yaml
    - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
      with:
        python-version: "3.12"
    - run: make check
    - run: make audit
    - run: make sbom
    - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
      with:
        name: sbom-cyclonedx
        path: sbom.cdx.json
```
Install Python 3.12 (the version the project targets). `make check` runs lint and unit tests (`make install` happens automatically through the stamp rule). `make audit` and `make sbom` are the supply-chain steps. `upload-artifact` stores the SBOM so it can be downloaded from the run page. If `make check` fails, the later steps do not run.

### Job `provider`

```yaml
provider:
  name: Integration and end-to-end tests against Keycloak 26
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@...
    - uses: actions/setup-python@...
    - run: make up
    - run: make test-integration test-e2e
    - if: always()
      run: make down
```
`make up` starts Keycloak 26 with Docker Compose (Docker is preinstalled on the runner), imports the demo realm and waits until the provider answers; it then runs `idp-check`, which fetches the discovery document and the signing keys. Then the integration tests (the provider adapter, token validation, the flow protections, refresh and sign-out) and the end-to-end test (a real server process and a scripted browser) run against it. `if: always()` makes the last step run even if an earlier one failed, so the containers are removed.

### How it mirrors local work

Every `run:` line is a `make` target a developer also runs. The workflow has almost no logic of its own, so it cannot drift from the `Makefile`.

### Check the file

`actionlint .github/workflows/ci.yml` (the workflow linter) reports no problems on this file.

## Try it yourself

1. Lint the workflow:
   ```bash
   actionlint .github/workflows/ci.yml && echo clean
   ```
   Expect `clean` (needs `actionlint` installed; `brew install actionlint`).
2. Find every action and check each is pinned to a 40-character SHA:
   ```bash
   grep -n "uses:" .github/workflows/ci.yml
   ```
   Expect five `uses:` lines, each `@` followed by 40 hex characters and a `# vX.Y.Z` comment.
3. Reproduce the job locally, step by step:
   ```bash
   make check && make audit && make sbom
   ```
   Expect everything to pass and `wrote sbom.cdx.json`.
4. After pushing to GitHub, open the repository's Actions tab and look for two jobs, `check` and `provider`, and the artifact `sbom-cyclonedx`. (This repository has not been pushed, so the hosted run has not happened; the commands above are what it will execute.)

## Mistakes people make

- Pinning actions to tags (`@v4`) or branches. Use a full commit SHA and keep the version in a comment.
- Granting the token more permission than needed. Start from `contents: read`.
- Letting `checkout` keep credentials.
- Putting secrets in `run:` text or echoing them to logs.
- Workflows that do things the `Makefile` cannot do locally, so failures cannot be reproduced.
- Forgetting cleanup of started services (`if: always()`).

## Check yourself

1. What is the difference between a job and a step?
   *A job is one machine's work; steps are the ordered commands or actions inside it.*
2. Why pin an action by commit SHA?
   *Tags can be moved; a SHA cannot be changed.*
3. What does `permissions: contents: read` do?
   *Limits the workflow token to reading the repository.*
4. Why `if: always()` on `make down`?
   *The cleanup must run even when a previous step failed.*
5. Do the two jobs run one after the other?
   *No; without `needs:` they run in parallel.*

## Further reading

- GitHub Actions documentation: https://docs.github.com/en/actions
- Workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- Security hardening for Actions (pin to a SHA, least privilege): https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
- actionlint: https://github.com/rhysd/actionlint
