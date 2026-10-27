# Docker Compose

## What it is

Docker Compose describes and runs a group of containers from one file, `docker-compose.yml` (format: `tech/yaml.md`). Instead of typing a long `docker run` command per container, you declare **services** (each becomes a container), their images, ports, environment variables, mounted files and start order, and then run `docker compose up`. It ships with Docker Desktop as the command `docker compose`.

## Why this repository uses it

The lesson signs in against a real OpenID Connect provider. Compose starts Keycloak (`tech/keycloak.md`) with a ready-made demo realm, the same way on a laptop and in CI, and deleting everything afterwards is one command (`docker compose down -v`). The same file can also run the app itself as a hardened container.

## Where it appears

| Path | What it does |
| --- | --- |
| `docker-compose.yml` | Two services: `keycloak` (always) and `app` (only with the `app` profile). 53 lines. |
| `Makefile` | `up` (`docker compose up -d --wait keycloak`), `docker-run`, `down`. |
| `.github/workflows/ci.yml` | `make up` and `make down` in the `provider` job. |
| `idp/realm-demo.json` | Mounted into the Keycloak container (see below). |
| `.env` / `.env.example` | The values Compose substitutes (not displayed in these notes; names are listed in `tech/dotenv.md`). |

## How it works underneath

1. Compose reads `docker-compose.yml` and a `.env` file in the same folder. Variables in `.env` fill `${NAME}` placeholders in the YAML.
2. It creates a private virtual network for the project (the `name:` key names it). Services reach each other by service name: the app container reaches the provider as `keycloak`.
3. For each service it pulls or builds the image, creates a container and starts it, in dependency order.
4. `--wait` blocks until services with a health check report healthy.
5. `down` stops and removes the containers and the network; `-v` also deletes their volumes.

## Walkthrough of this repository's use

```yaml
name: security-oauth-login-done-right
```
The project name; prefixes container and network names.

### The `keycloak` service

```yaml
keycloak:
  image: quay.io/keycloak/keycloak:26.4
  command: ["start-dev", "--import-realm"]
  ports:
    - "127.0.0.1:${KEYCLOAK_PORT:-8180}:8080"
```
The official Keycloak 26.4 image from the Quay registry. `command` is passed to Keycloak's launcher: `start-dev` runs it in **development mode** (plain HTTP, an embedded file database, no production hardening; fine for a lesson, never for real use) and `--import-realm` makes it read realm files from its import folder at start-up. The published port maps container port 8080 to host port 8180 (override with `KEYCLOAK_PORT`), bound to the loopback address only, so only your own machine reaches it.

```yaml
  environment:
    KC_BOOTSTRAP_ADMIN_USERNAME: ${KEYCLOAK_ADMIN:-admin}
    KC_BOOTSTRAP_ADMIN_PASSWORD: ${KEYCLOAK_ADMIN_PASSWORD:?copy .env.example to .env first}
    KC_HEALTH_ENABLED: "true"
```
`KC_*` variables are Keycloak's configuration. The bootstrap admin account is created on first start; its password has no default: `${VAR:?message}` stops Compose with that message when the variable is missing. `KC_HEALTH_ENABLED` turns on the `/health` endpoints on the management port (9000).

```yaml
    KC_HOSTNAME: http://localhost:${KEYCLOAK_PORT:-8180}
    KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"
```
This pair solves a real problem. A token's **issuer** (`iss`) is a URL, and the app must see the same issuer however it reaches the provider. The browser reaches Keycloak at `http://localhost:8180`; the app container reaches it at `http://keycloak:8080`. `KC_HOSTNAME` fixes the issuer and the browser-facing URLs to the first; `KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"` lets server-to-server URLs (token, keys) follow whatever host the caller used. So the app can use `OIDC_DISCOVERY_BASE=http://keycloak:8080/realms/demo` and still get tokens with the browser-facing issuer, which it checks exactly.

```yaml
    NOTES_APP_CLIENT_SECRET: ${OIDC_CLIENT_SECRET:?copy .env.example to .env first}
    DEMO_USER_PASSWORD: ${DEMO_USER_PASSWORD:?copy .env.example to .env first}
    APP_BASE_URL: http://localhost:${APP_PORT:-3000}
```
These three become environment variables inside the Keycloak container. Keycloak replaces the matching `${NOTES_APP_CLIENT_SECRET}`, `${DEMO_USER_PASSWORD}` and `${APP_BASE_URL}` placeholders inside the realm file while importing it, so the realm file in git contains no secret. The registered redirect URI becomes `http://localhost:3000/callback`.

```yaml
  volumes:
    - ./idp/realm-demo.json:/opt/keycloak/data/import/realm-demo.json:ro
```
A **bind mount**: the host file appears inside the container at Keycloak's import path. `:ro` makes it read-only inside.

```yaml
  healthcheck:
    test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/9000 && printf 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3 && grep -q '\"status\": \"UP\"' <&3"]
    interval: 5s
    timeout: 5s
    retries: 120
    start_period: 20s
```
The Keycloak image has no `curl`, so the check uses Bash's built-in network device `/dev/tcp` (see `tech/bash.md`): open a TCP connection to the management port as file descriptor 3, send a hand-written HTTP request, and `grep` the reply for `"status": "UP"`. The service is healthy only after the realm import finished. Check every 5 seconds, allow up to 120 failures (10 minutes: Keycloak's first start is slow, especially on a loaded machine), and ignore failures during the first 20 seconds.

### The `app` service

```yaml
app:
  profiles: ["app"]
  build: .
  image: security-oauth-login-done-right:dev
  depends_on:
    keycloak:
      condition: service_healthy
  env_file: .env
  environment:
    APP_HOST: 0.0.0.0
    OIDC_DISCOVERY_BASE: http://keycloak:8080/realms/demo
```
`profiles` means it starts only when you ask (`--profile app`), so `make up` starts just Keycloak. It builds the Dockerfile here (`tech/docker.md`) and waits for Keycloak to be healthy. `env_file` loads the whole `.env` (issuer, client id and secret, redirect URI). The two overrides: listen on all interfaces inside the container, and fetch the discovery document and keys from Keycloak by its service name.

```yaml
  ports:
    - "127.0.0.1:${APP_PORT:-3000}:${APP_PORT:-3000}"
  read_only: true
  tmpfs:
    - /tmp
  cap_drop:
    - ALL
  security_opt:
    - no-new-privileges:true
```
Publish the app on the loopback only. Read-only root file system with a RAM-backed `/tmp`. No Linux capabilities. No privilege gain. See `tech/docker.md`.

### The commands the Makefile uses

- `docker compose up -d --wait keycloak`: start only Keycloak, detached, wait for healthy. Then `make idp-check` fetches the discovery document and the keys with `curl` (`tech/curl.md`).
- `docker compose --profile app up -d --wait --build app`: build and start the app, wait for its image health check.
- `docker compose --profile app down -v`: remove containers, network and data.

## Try it yourself

1. Check the file without starting anything:
   ```bash
   docker compose --profile app config --quiet && echo valid
   ```
   Expect `valid` (needs the Docker CLI but not a running engine, and a `.env`; run `make env` to create one).
2. See the resolved configuration (it contains local secrets: do not paste it anywhere):
   ```bash
   docker compose --profile app config | head -40
   ```
   Expect `app` and `keycloak` with every `${...}` replaced.
3. Start the provider (slow the first time; needs Docker and free disk space):
   ```bash
   make up && docker compose ps
   ```
   Expect `keycloak` `running (healthy)` and the `idp-check` lines: the issuer, the authorization endpoint, the keys URI and `signing keys` with a count.
4. Prove the loopback-only binding:
   ```bash
   docker compose ps --format '{{.Ports}}'
   ```
   Expect `127.0.0.1:8180->8080/tcp`.
5. Clean up: `make down`.

(These need the Docker engine. On the night this note was written the engine's disk was full, so steps 3 to 5 were not re-run; steps 1 and 2 were.)

## Mistakes people make

- Publishing the provider on all interfaces. Here it is loopback only.
- Writing secrets in the compose file or the realm file. Placeholders are filled from `.env`.
- Using `depends_on` without a health condition: "started" is not "ready".
- Letting the issuer differ between the browser and the back channel. The `KC_HOSTNAME` pair prevents it.
- Using `start-dev` outside a lesson.
- Editing the realm file and expecting a running Keycloak to notice. The import runs only when the realm does not exist yet; `make down` (which deletes the data) and `make up` re-import it.
- Not giving Keycloak enough start-up time. `retries: 120` at 5 seconds allows ten minutes.

## Check yourself

1. What does `--import-realm` do together with the mounted file?
   *Keycloak creates the realm described by the file when it starts.*
2. Why does the Keycloak healthcheck not use `curl`?
   *The image has none; Bash's `/dev/tcp` and `printf` send the HTTP request.*
3. What does `${KEYCLOAK_ADMIN_PASSWORD:?message}` do?
   *Stops with the message if the variable is empty.*
4. Why two different hostnames for Keycloak (browser and app)?
   *The browser reaches it as `localhost:8180`, the container as `keycloak:8080`; `KC_HOSTNAME` plus dynamic back-channel keeps the issuer constant.*
5. What does a profile do?
   *The service starts only when that profile is requested.*

## Further reading

- Compose file reference: https://docs.docker.com/reference/compose-file/
- Interpolation (`:-`, `:?`): https://docs.docker.com/reference/compose-file/interpolation/
- Profiles: https://docs.docker.com/compose/how-tos/profiles/
- Keycloak container guide: https://www.keycloak.org/server/containers
- Keycloak hostname options (version 26): https://www.keycloak.org/server/hostname
