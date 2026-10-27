# JSON

## What it is

JSON (JavaScript Object Notation) is a text format for structured data. It has six kinds of value: an **object** (`{"key": value, ...}`, a set of named values), an **array** (`[1, 2, 3]`), a **string** (`"text"` in double quotes), a **number**, `true`/`false`, and `null`. It is the language of web APIs, and also of several configuration files. Python's standard library reads and writes it with the `json` module: an object becomes a `dict`, an array a `list`.

## Why this repository uses it

JSON is everywhere in this lesson, not in one place:

- the realm definition for Keycloak is a JSON file (`idp/realm-demo.json`);
- the provider's discovery document and key set are JSON documents;
- the token endpoint replies in JSON, and errors come back as `{"error": "invalid_grant", ...}`;
- the header and payload of every JWT are JSON (`tech/jwt-and-jwks.md`);
- the app's own API (`/me`, `/refresh`, `/reports`, error responses) answers in JSON;
- the logs are one JSON object per line, and the SBOM is JSON.

## Where it appears

| Path | What it does with JSON |
| --- | --- |
| `idp/realm-demo.json` | Keycloak realm: settings, scopes, clients, user (180 lines). |
| `src/oidc_login/infrastructure/logging.py` | `json.dumps(payload, default=str, separators=(",", ":"))`: one compact line per log record. |
| `src/oidc_login/interfaces/http/app.py` | `jsonify(...)` for responses. |
| `src/oidc_login/infrastructure/oidc_provider.py` | `response.json()` on every provider reply, then strict type checks. |
| `Makefile` (`idp-check`) | `json.load(sys.stdin)` to print three fields from the discovery document. |
| `sbom.cdx.json` | The software bill of materials (`tech/cyclonedx.md`). |

## How it works underneath

- **Parsing** turns text into in-memory values; **serializing** does the reverse. Both are strict: a trailing comma, a single-quoted string or a comment is a syntax error.
- Keys are always strings. Numbers have no int/float distinction in the text. Unicode is allowed; `\n`, `\"` and `\\` are the usual escapes.
- JSON has **no comment syntax**, which matters for the realm file: its explanations live in the `description` fields and in `docker-compose.yml`'s comments, not in the file.
- JSON from outside is **untrusted input**. A parsed value might not be a dictionary at all, or lack the key you expect, or hold a number where you expected text.

### Ideas you need first

- **Data as text.** A format lets two programs exchange structured data by writing and reading text.
- **An object, an array, a string, a number.** A JSON object is `{"key": value}`; an array is `[a, b]`; a string is in double quotes; numbers are bare; `true`, `false` and `null` complete the set.
- **Parsing.** Reading JSON text into Python dictionaries and lists. Bad JSON raises an error.
- **A placeholder.** In the realm file, `${NAME}` is not JSON syntax; Keycloak replaces it with an environment variable when it imports the file.

## Walkthrough of this repository's use

### The realm file

Its structure (details in `tech/keycloak.md`):

```json
{
  "realm": "demo",
  "enabled": true,
  "accessTokenLifespan": 120,
  "clientScopes": [ { "name": "profile", "protocolMappers": [ ... ] }, ... ],
  "clients": [ { "clientId": "notes-app", "redirectUris": ["${APP_BASE_URL}/callback"], ... } ],
  "users": [ { "username": "demo-user", "credentials": [ { "type": "password", "value": "${DEMO_USER_PASSWORD}" } ] } ]
}
```
Top-level object with scalar settings (`realm` is a string, `enabled` a boolean, `accessTokenLifespan` a number of seconds) and three arrays of objects. `${NAME}` inside a string is not JSON syntax; Keycloak replaces it from the environment at import. Because JSON has no comments, you cannot disable a line by commenting it out.

### Safe reading of a reply

```python
body = response.json()
return body if isinstance(body, dict) else {}
```
The provider's reply might parse as a list or a string. Every use checks the type first. `_token_request` builds a typed object from `str(body["access_token"])`, `int(body["expires_in"])` and catches `(ValueError, KeyError, TypeError)` for anything off-shape, so a malformed reply becomes a `ProviderError("invalid_response", ...)` and not a crash.

### Logs as JSON lines

```python
return json.dumps(payload, default=str, separators=(",", ":"))
```
`separators=(",", ":")` removes the spaces, so each log record is one short line with no newline inside (log tools split on newlines). `default=str` turns anything JSON cannot represent (a date, a set) into its text instead of raising an error, so logging never fails. Before this, `redact(...)` replaces the value of any field whose name looks sensitive (`token`, `code`, `state`, `nonce`, `verifier`, `session`, `secret`, ...) with `[redacted]`.

### The Makefile one-liner

```make
@curl -fsS $(OIDC_ISSUER)/.well-known/openid-configuration | $(PY) -c "import json,sys; d=json.load(sys.stdin); print('issuer                ', d['issuer']); ..."
```
`json.load(sys.stdin)` parses what `curl` printed; the script prints three fields (`tech/curl.md`, `tech/bash.md`).

## Try it yourself

1. Check that the realm file is valid JSON and list its parts:
   ```bash
   python3 -c "import json; d = json.load(open('idp/realm-demo.json')); print(d['realm'], [c['clientId'] for c in d['clients']], [s['name'] for s in d['clientScopes']])"
   ```
   Expect `demo ['notes-app', 'notes-spa'] ['profile', 'email', 'reports:read']`.
2. Pretty-print one part:
   ```bash
   python3 -c "import json; print(json.dumps(json.load(open('idp/realm-demo.json'))['clients'][0]['attributes'], indent=2))"
   ```
   Expect `pkce.code.challenge.method`, `post.logout.redirect.uris`, `use.refresh.tokens`.
3. See a syntax error:
   ```bash
   echo '{"a": 1,}' | python3 -m json.tool
   ```
   Expect `Illegal trailing comma before end of object` (a trailing comma is not allowed in JSON).
4. See the redaction in logs:
   ```bash
   .venv/bin/python -c "
   from oidc_login.infrastructure.logging import redact
   print(redact({'event': 'login.started', 'state': 'abc', 'subject': 'u1'}))"
   ```
   Expect `{'event': 'login.started', 'state': '[redacted]', 'subject': 'u1'}`.

## Mistakes people make

- Trailing commas, single quotes or comments in a `.json` file.
- Assuming a parsed value has the type and keys you expect.
- Logging whole request or response bodies.
- Putting secrets in a JSON file in git. The realm uses `${...}` placeholders.
- Pretty-printed multi-line log records, which break line-based log tools.
- Relying on key order.

## Check yourself

1. What are the six kinds of JSON value?
   *Object, array, string, number, boolean (`true`/`false`) and `null`.*
2. Can a JSON file have comments?
   *No.*
3. Why does `json.dumps` in the logger use `separators=(",", ":")`?
   *To print compact single-line records.*
4. What does `isinstance(body, dict)` protect against?
   *A reply that is valid JSON but not an object.*
5. What turns `${APP_BASE_URL}` into a real value?
   *Keycloak, when it imports the realm, using environment variables.*

## Further reading

- json.org: https://www.json.org/
- RFC 8259 (the JSON standard): https://www.rfc-editor.org/rfc/rfc8259
- Python `json`: https://docs.python.org/3.12/library/json.html
