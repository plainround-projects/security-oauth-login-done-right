# Technology notes

These notes teach every technology this repository uses, from zero, through the repository's own files. You do not need to know any of them first. Each note says what the technology is, why it is here, where it appears, how it works underneath, walks through this repository's actual lines, gives commands to try, lists common mistakes and ends with five questions.

Notes describe the code as committed. Commands that need the identity provider say `needs make up`; commands that need Docker say so. Where a command was not re-run when the note was written, the note says that too.

## Ten minutes? Read these three

1. [oauth2-and-openid-connect.md](oauth2-and-openid-connect.md): the protocol and the whole flow, step by step.
2. [jwt-and-jwks.md](jwt-and-jwks.md): what an ID token is and why the signature check is written the way it is.
3. [http-cookies-csrf-and-headers.md](http-cookies-csrf-and-headers.md): the two cookies, `state`, and why `SameSite=Lax`.

## Reading order

**1. The language and the command line**

| Note | Role here |
| --- | --- |
| [python.md](python.md) | Python 3.12: the language of the app, the tests and the demo. |
| [bash.md](bash.md) | The shell fragments in the Makefile and Keycloak's hand-written health check. |
| [make.md](make.md) | The `Makefile`: one short command per task. |
| [curl.md](curl.md) | The check that the provider is up and publishes its keys. |
| [git.md](git.md) | History, and `.gitignore` for files that must never be committed. |
| [editorconfig.md](editorconfig.md) | Editor settings shared by everyone. |

**2. Files and formats**

| Note | Role here |
| --- | --- |
| [toml.md](toml.md) | The format of `pyproject.toml`. |
| [yaml.md](yaml.md) | The format of the compose file and the workflow. |
| [json.md](json.md) | The realm file, provider replies, JWT contents, JSON logs. |
| [dotenv.md](dotenv.md) | `.env` files and environment variables: where configuration and secrets come from. |
| [pyproject-and-setuptools.md](pyproject-and-setuptools.md) | Turning `src/` into an installable package with two commands. |
| [uv-and-lock-files.md](uv-and-lock-files.md) | venv, pip, uv and the hash-pinned lock files. |

**3. The protocol and the identity provider**

| Note | Role here |
| --- | --- |
| [oauth2-and-openid-connect.md](oauth2-and-openid-connect.md) | Authorization code flow, scopes, `state`, `nonce`, refresh rotation, revocation. |
| [pkce.md](pkce.md) | The verifier and the challenge that make a stolen code useless. |
| [jwt-and-jwks.md](jwt-and-jwks.md) | Signed tokens, key sets, algorithm confusion. |
| [pyjwt.md](pyjwt.md) | The library that verifies signatures, and `cryptography` under it. |
| [keycloak.md](keycloak.md) | The local identity provider and its realm file. |
| [httpx.md](httpx.md) | The HTTP client for the back channel: timeouts, retries, no redirects. |

**4. The web application**

| Note | Role here |
| --- | --- |
| [flask.md](flask.md) | The web framework: routes, hooks, error handlers. |
| [werkzeug.md](werkzeug.md) | The library under Flask: proxy handling, errors, cookies, the test client. |
| [jinja2-templates.md](jinja2-templates.md) | HTML templates and output encoding. |
| [gunicorn.md](gunicorn.md) | The production server, one worker, graceful shutdown. |
| [http-cookies-csrf-and-headers.md](http-cookies-csrf-and-headers.md) | Cookies, CSRF tokens, security headers. |

**5. Containers and delivery**

| Note | Role here |
| --- | --- |
| [docker.md](docker.md) | The Dockerfile and a hardened image. |
| [docker-compose.md](docker-compose.md) | Keycloak and the app as one stack. |
| [github-actions.md](github-actions.md) | CI that runs the same `make` targets. |

**6. Tests and quality**

| Note | Role here |
| --- | --- |
| [pytest.md](pytest.md) | Unit, integration and end-to-end tests, and the coverage gate. |
| [ruff.md](ruff.md) | Linting (with security rules) and formatting. |
| [mypy.md](mypy.md) | Static type checking. |
| [import-linter.md](import-linter.md) | Architecture rules enforced as a build step. |
| [pip-audit.md](pip-audit.md) | Known-vulnerability check on the locked dependencies. |
| [cyclonedx.md](cyclonedx.md) | The software bill of materials. |
