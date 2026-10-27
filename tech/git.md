# Git and `.gitignore`

## What it is

Git is a **version control system**: it records the history of a folder as a chain of **commits**, each a snapshot with an author, a time and a message. You can see what changed, return to an earlier snapshot, and work on several lines of history (**branches**) at once. A **repository** is the folder plus its hidden `.git` database. `.gitignore` is a text file listing the names of files git must never track.

## Why this repository uses it

The lesson's controls are only trustworthy if their history is reviewable: each commit adds one control with its test. And git is where the worst security mistake lives: a secret committed once stays in history even after it is deleted. The `.gitignore` is the first defense against committing the local `.env`, the virtual environment and generated reports.

## Where it appears

| Path | What it does |
| --- | --- |
| `.git/` | The history (about ten commits, one per step: skeleton, provider and keys, the flow, token checks, sessions and refresh, protections, CI, fixes, these notes). |
| `.gitignore` | 17 patterns of files never committed. |
| `.dockerignore` | The same idea for the Docker build context (`tech/docker.md`). |
| `.github/workflows/ci.yml` | Runs on git pushes (`tech/github-actions.md`). |

## How it works underneath

1. `git add file` copies the file's current content into the **staging area** (the next snapshot).
2. `git commit -m "message"` stores the staged snapshot as a new commit, identified by a SHA hash of its content and its parent commit. Because each commit contains its parent's hash, changing history changes every later hash.
3. `git status` compares three things: the last commit, the staging area and the working folder.
4. A path matching a pattern in `.gitignore` is invisible to `git add .` and `git status`. It does **not** untrack a file already committed.

## Walkthrough of this repository's use

```
.venv/
__pycache__/
*.pyc
*.egg-info/
build/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.import_linter_cache/
.coverage
coverage.xml
.env
.DS_Store
logs/
sbom.cdx.json
.omc/
```
- A trailing `/` means a folder. `*.pyc` is a wildcard for compiled Python files.
- `.venv/`, the tool caches (`.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.import_linter_cache/`), `.coverage`, `coverage.xml`, `build/`, `dist/`, `*.egg-info/` are generated, large and machine-specific.
- `.env` holds local passwords. It is ignored; `.env.example` is not, so a fresh clone can copy the example. (`make env` does the copy.)
- `sbom.cdx.json` is a build output (`tech/cyclonedx.md`); `logs/` holds local server logs.
- `.omc/` is a local tool's work folder; `.DS_Store` is a macOS Finder file.

### Commit hygiene in this repository

Commits are one logical step each, with a message that says what and why. No credential appears in any file: the client secret and the demo user's password are placeholders (`${NOTES_APP_CLIENT_SECRET}`, `${DEMO_USER_PASSWORD}`) that Keycloak fills from the environment, and `.env.example` holds local-only values. A secret scanner for history is the topic of the pipeline lesson (`security-secure-the-pipeline`).

## Try it yourself

1. See the history:
   ```bash
   git log --oneline
   ```
   Expect about ten lines, newest first.
2. Check why a file is ignored:
   ```bash
   git check-ignore -v .env sbom.cdx.json .venv
   ```
   Expect each path listed with the `.gitignore` line number that matches.
3. See what git would add:
   ```bash
   git status --short
   ```
   Expect nothing for generated folders.
4. See one commit's change:
   ```bash
   git show --stat HEAD
   ```
   Expect the commit message and a list of changed files.

## Mistakes people make

- Committing a secret and then "deleting" it in a later commit. It remains in history; rotate the secret.
- Adding a file to `.gitignore` after committing it; git keeps tracking it until `git rm --cached`.
- Huge "fix everything" commits that cannot be reviewed.
- Ignoring `.env.example`, so newcomers have no template.
- Committing generated artifacts (`sbom.cdx.json`, caches).

## Check yourself

1. What is a commit?
   *A stored snapshot with an author, time, message and a link to its parent.*
2. Does `.gitignore` remove a file already tracked?
   *No; it only affects untracked files.*
3. Why is `.env` ignored but `.env.example` tracked?
   *The first holds real local values; the second documents the names with safe placeholders.*
4. Why can history not be quietly edited?
   *Each commit's hash includes its parent's hash.*
5. What is the staging area?
   *The set of changes prepared for the next commit.*

## Further reading

- Pro Git book: https://git-scm.com/book/en/v2
- `gitignore` patterns: https://git-scm.com/docs/gitignore
- GitHub on removing sensitive data: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
