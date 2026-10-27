# YAML

## What it is

YAML ("YAML Ain't Markup Language") is a text format for structured data, designed to be easy to read. It stores the same things as JSON (key-value mappings, lists, strings, numbers, true/false) but uses **indentation** and dashes instead of braces and brackets. Two files in this repository are YAML: `docker-compose.yml` and `.github/workflows/ci.yml`.

## Why this repository uses it

Both Docker Compose and GitHub Actions require YAML for their configuration files; the format is not a choice of the lesson. Knowing its rules prevents the most common reason such files fail.

## Where it appears

| Path | What it does |
| --- | --- |
| `docker-compose.yml` | Describes the containers (`tech/docker-compose.md`). |
| `.github/workflows/ci.yml` | Describes the CI jobs (`tech/github-actions.md`). |

## How it works underneath

- **A mapping** is `key: value`. Nesting is shown by indenting the child lines with spaces (never tabs). Two spaces per level is the convention here (`.editorconfig` sets it for `yml`).
- **A sequence** (list) is lines starting with `- `, at the same indentation.
- **Scalars** are plain text, numbers, `true`/`false`, `null`. Quotes are optional unless the text could be misread.
- **Flow style** is JSON-like inline syntax: `[a, b]` or `{k: v}`. `on: [push, pull_request]` is a flow list.
- `#` starts a comment.
- A program (`docker compose`, GitHub) parses the text into dictionaries and lists in memory, then reads keys from them.

The classic trap: YAML guesses types. `NO`, `off` and `on` can become booleans, `1.10` becomes the number 1.1, and `0123` becomes the octal number 83. So ports and versions are quoted when it matters: `python-version: "3.12"` (unquoted, `3.10` would become `3.1`).

## Walkthrough of this repository's use

```yaml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.4
    command: ["start-dev", "--import-realm"]
    ports:
      - "127.0.0.1:${KEYCLOAK_PORT:-8180}:8080"
```
`services` is a mapping; `keycloak` is a key inside it; `image`, `command` and `ports` are keys inside that. `command` is a flow-style list of two strings. `ports` is a sequence with one item. The item is quoted because it contains colons, and `host:port` strings with colons can be misread as numbers (the "sexagesimal" trap in YAML 1.1).

```yaml
    environment:
      KC_HEALTH_ENABLED: "true"
      KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"
      APP_BASE_URL: http://localhost:${APP_PORT:-3000}
```
A mapping of variables. `"true"` is quoted on purpose: unquoted, YAML would make it a boolean, but the container needs the text `true`. `http://localhost:...` is a plain string; `${...}` is not YAML syntax at all, it is Compose's own placeholder, replaced before the container sees it.

```yaml
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/9000 && printf 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3 && grep -q '\"status\": \"UP\"' <&3"]
      interval: 5s
```
A double-quoted YAML string uses backslash escapes, so the file doubles each backslash (`\\r` is the text `\r` that the shell's `printf` then turns into a carriage return) and escapes the inner double quotes (`\"`). The duration `5s` is a string Compose understands, not a YAML type.

```yaml
steps:
  - uses: actions/checkout@3d3c42e5... # v7.0.1
    with:
      persist-credentials: false
  - run: make check
```
A sequence of two mappings. A `-` begins each item; the keys of one item line up under the first key. `persist-credentials: false` is a real boolean. The `# v7.0.1` comment is not part of the value (a space before `#` is required).

```yaml
  - if: always()
    run: make down
```
Keys of one item: `if` (a GitHub expression, written as text) and `run`.

## Try it yourself

1. Parse a file and print it as Python data (needs PyYAML; it is not in this project's environment, so use a throwaway one):
   ```bash
   python3 -m venv /tmp/yamlenv && /tmp/yamlenv/bin/pip install -q pyyaml && /tmp/yamlenv/bin/python -c "import yaml, pprint; pprint.pprint(yaml.safe_load(open('docker-compose.yml'))['services']['keycloak']['ports'])"
   ```
   Expect `['127.0.0.1:${KEYCLOAK_PORT:-8180}:8080']`. (Delete `/tmp/yamlenv` afterwards.)
2. See the type guessing:
   ```bash
   /tmp/yamlenv/bin/python -c "import yaml; print(yaml.safe_load('a: 3.10\nb: \"3.10\"\nc: no'))"
   ```
   Expect `{'a': 3.1, 'b': '3.10', 'c': False}` (PyYAML implements YAML 1.1: `no` is false, `3.10` loses its zero).
3. Validate Compose's reading of the file:
   ```bash
   docker compose --profile app config --quiet && echo valid
   ```
   Expect `valid`.
4. Validate the workflow's syntax and semantics: `actionlint .github/workflows/ci.yml`. Expect no output.

## Mistakes people make

- Using tabs for indentation: a YAML error.
- Misaligned list items: the item's keys must line up.
- Unquoted values that look like something else (`3.10`, `no`, `on`, `1:2`).
- Forgetting the space after `:` or `-`.
- Putting secrets in YAML files committed to git. Here the values are placeholders (`${VAR}`).

## Check yourself

1. How does YAML show that one key belongs inside another?
   *By indenting it with spaces.*
2. What is wrong with `python-version: 3.10`?
   *It parses as the number 3.1; quote it as `"3.10"`.*
3. What does `- run: make check` represent?
   *A list item that is a mapping with one key, `run`.*
4. Are tabs allowed for indentation?
   *No.*
5. How do you write a comment?
   *With `#` preceded by a space (or at line start).*

## Further reading

- YAML 1.2.2 specification: https://yaml.org/spec/1.2.2/
- Learn YAML in Y minutes: https://learnxinyminutes.com/yaml/
- Compose file reference: https://docs.docker.com/reference/compose-file/
- Workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
