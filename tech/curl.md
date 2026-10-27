# curl

## What it is

`curl` is a command-line program that makes network requests and prints the reply. Give it a URL and it sends an HTTP request (GET by default) and writes the response body to your terminal (standard output). It is installed on macOS and most Linux systems, and it is the standard way to poke at a web server by hand.

## Why this repository uses it

After `make up`, one question matters before anything else: is the identity provider really up and publishing its discovery document and signing keys? `make idp-check` answers by asking the provider with `curl`, once for each. The README and these notes also use `curl` to show raw responses (headers, cookies, status codes), because seeing the plain HTTP text makes the protocol real.

## Where it appears

| Path | What it does with curl |
| --- | --- |
| `Makefile` target `idp-check` | Two `curl -fsS` calls piped into a short Python program. |
| `tech/*.md` | Try-it commands such as `curl -si http://127.0.0.1:3000/healthz`. |

(The containers do not use `curl`: the app's health check is the Python program `oidc-login-health`, and the Keycloak image has no `curl`, which is why its health check uses Bash's `/dev/tcp`, `tech/bash.md`.)

## How it works underneath

1. `curl URL` opens a TCP connection to the host and port in the URL (a TLS session first for `https`), writes `GET /path HTTP/1.1` plus headers, reads the reply, prints the body, and exits.
2. The **exit code** tells whether the transfer worked: 0 for success; non-zero for failures such as "could not connect" (7) or, with `-f`, an HTTP error status (22).
3. By default `curl` prints the body even for a 404 or 500 and exits 0. The `-f` flag changes that.

### Ideas you need first

- **A URL.** An address such as `http://localhost:8180/realms/demo`: scheme (`http`), host (`localhost`), port (`8180`) and path.
- **A request and a response.** `curl` sends a request and prints the response body. With `-i` it also prints the status line and headers.
- **An exit code.** A number a program returns: 0 for success. Scripts check it.

## Walkthrough of this repository's use

```make
idp-check: ## step 1: the discovery document and the signing keys are reachable
	@curl -fsS $(OIDC_ISSUER)/.well-known/openid-configuration | $(PY) -c "import json,sys; d=json.load(sys.stdin); print('issuer                ', d['issuer']); print('authorization_endpoint', d['authorization_endpoint']); print('jwks_uri              ', d['jwks_uri'])"
	@curl -fsS $(OIDC_ISSUER)/protocol/openid-connect/certs | $(PY) -c "import json,sys; print('signing keys          ', len(json.load(sys.stdin)['keys']))"
```
- `-f` (`--fail`): treat an HTTP error status (4xx/5xx) as a failure with a non-zero exit code and print nothing, so a provider that answers 404 cannot pass for healthy.
- `-s` (`--silent`): no progress meter, which would clutter the output and the pipe.
- `-S` (`--show-error`): but still print an error message if it fails. `-s` alone would hide it.
- `$(OIDC_ISSUER)` is a Make variable from `.env` (`tech/dotenv.md`): `http://localhost:8180/realms/demo`.
- The `|` pipe feeds the body to `python -c "..."`, which parses it (`tech/json.md`) and prints three fields; the second call counts the signing keys in the key set.
- The leading `@` hides the long command from `make`'s echo.
- With the `pipefail` behavior absent in a plain Make recipe, a failed `curl` shows up because Python then fails to parse empty input and exits non-zero, so the target fails either way.

## Try it yourself

(Needs Keycloak: `make up`.)

1. Run the check:
   ```bash
   make idp-check
   ```
   Expect `issuer`, `authorization_endpoint`, `jwks_uri` and `signing keys` followed by a count (2 in the verified run: Keycloak publishes more than one key).
2. See the raw reply with headers:
   ```bash
   curl -si http://localhost:8180/realms/demo/.well-known/openid-configuration | head -15
   ```
   Expect `HTTP/1.1 200 OK` and `Content-Type: application/json`. `-i` prints the response headers.
3. See `-f` at work against a path that does not exist:
   ```bash
   curl -fsS http://localhost:8180/realms/nope/.well-known/openid-configuration; echo "exit $?"
   ```
   Expect an error line ending in `error: 404` and `exit 22`.
4. Look at the app's headers while it runs (`make run`):
   ```bash
   curl -si http://localhost:3000/healthz
   ```
   Expect `200 OK`, the body `{"status":"ok"}`, and the security headers (`tech/http-cookies-csrf-and-headers.md`).

## Mistakes people make

- Forgetting `-f` in scripts, so a 404 looks like success.
- Using `-k` / `--insecure` to silence certificate errors, which disables the protection of TLS.
- Putting secrets on the command line, where other users' `ps` can see them and the shell history keeps them.
- Not quoting URLs that contain `&`, which the shell treats as "run in background".
- Following redirects blindly with `-L` while sending credentials.

## Check yourself

1. What does `-f` change?
   *HTTP error statuses make curl fail with a non-zero exit code.*
2. What do `-s` and `-S` do together?
   *Silence progress output but still show errors.*
3. How does `idp-check` read the JSON?
   *It pipes curl's output to a Python one-liner that parses it.*
4. What does `-i` print?
   *The response headers before the body.*
5. Why does the Keycloak container not use curl for its health check?
   *The image does not contain it.*

## Further reading

- curl documentation: https://curl.se/docs/
- Man page (all options): https://curl.se/docs/manpage.html
- Exit codes: https://curl.se/docs/manpage.html#EXIT
