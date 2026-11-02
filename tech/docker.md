# Docker and the Dockerfile

## What it is

**Docker** packages a program together with everything it needs (the Python interpreter, libraries, files) into an **image**: a read-only template. A **container** is a running instance of an image: an ordinary process on your machine, but isolated, with its own view of the file system, network and process list. A **Dockerfile** is the recipe text file that says how to build an image, one instruction per step. On macOS the containers run inside a small Linux virtual machine that Docker Desktop manages.

An image is made of **layers**, one per instruction that changes files. Docker caches each layer and reuses it if the instruction and everything before it are unchanged.

## Why this repository uses it

Two reasons. First, the identity provider (Keycloak) runs as a container (`tech/docker-compose.md`), so the lesson needs no provider account or installation. Second, the app itself is also packaged as an image to show a **hardened runtime**: a base image fixed by digest, hash-checked dependencies, a non-root user, a health check, no packaging tools left inside, and run-time restrictions (read-only file system, no Linux capabilities).

## Where it appears

| Path | What it does |
| --- | --- |
| `Dockerfile` | Builds the `security-oauth-login-done-right:dev` image (27 lines). |
| `.dockerignore` | Keeps `.git`, `.venv`, `.env*`, caches, `tests`, `docs`, `logs`, `.github` out of the build context. |
| `Makefile` | `docker-build`, `docker-run`, `down`. |
| `docker-compose.yml` | Builds and runs the image under the `app` profile. |

## How it works underneath

1. `docker build .` sends the **build context** (the folder, minus `.dockerignore` entries) to the Docker engine.
2. The engine runs the instructions in order. `FROM` picks a base image; every later instruction runs on top and produces a layer.
3. `RUN` executes a command in a temporary container and saves the file changes as a layer. `COPY` adds files from the build context.
4. The result is stored by a **digest**: a SHA-256 of its content. A **tag** like `3.12-slim-bookworm` is a movable label; a digest is not.
5. `docker run` / `docker compose up` creates a container, starts the `CMD` as process number 1, and attaches the isolation settings.
6. Stopping sends `SIGTERM` to process 1, then `SIGKILL` after a grace period (10 seconds by default). Process 1 here is gunicorn, which handles `SIGTERM` gracefully (`tech/gunicorn.md`).

### Ideas you need first

- **An operating system and a kernel.** The kernel is the core of an operating system: it runs programs and controls memory, files and the network. A container is a normal program started by the kernel with a restricted view of the system.
- **A process and process number 1.** Every running program is a process. In a container the first process (the one named by `CMD`) is process number 1: it receives the stop signal that Docker sends, so it must handle it.
- **A signal and graceful shutdown.** A signal is a short message from the operating system to a process. `SIGTERM` means "please stop"; a program that handles it can finish its work and exit cleanly. After a grace period Docker sends `SIGKILL`, which ends the process at once.
- **A user and root.** Every process runs as a user. `root` can do anything on the machine (inside a container: anything the container is allowed). A **non-root** user cannot write system files or install software, so a compromise does less damage.
- **A file system and a layer.** An image's files are a stack of read-only layers. A running container adds a thin writable layer on top, unless it is run **read-only**.
- **A cache.** Docker reuses a layer if the instruction and everything before it are unchanged, which is why the dependency files are copied before the source code.
- **A health check.** A command Docker runs inside the container at intervals; exit code 0 means healthy.
- **A registry.** A server that stores images so they can be pulled by name. This repository pulls the base image (`python`) and the database or provider image (`postgres`, `keycloak`) from public registries and does not run one of its own.

## Walkthrough of this repository's use

```dockerfile
FROM python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753
```
Start from the official Python 3.12 image on Debian 12 ("bookworm"), the `slim` variant (smaller). The `@sha256:...` pins the exact image content: if someone re-publishes the tag with different content, the build still gets the reviewed one, or fails.

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
```
Environment variables for every later instruction and for the running container. No `.pyc` files (the file system may be read-only); no output buffering (logs appear immediately); pip keeps no download cache (smaller image) and does not phone home to check for a new version.

```dockerfile
WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
```
Work in `/app`. Copy only the lock file and install from it, hash-checked (`tech/uv-and-lock-files.md`). Because this layer depends only on `requirements.lock`, Docker reuses it on every rebuild unless the lock changes.

```dockerfile
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .
```
Now the project: its metadata and source. `--no-deps` stops pip from resolving or fetching anything not in the lock.

```dockerfile
RUN pip uninstall -y pip setuptools
```
The packaging tools are not needed to run the service, and their vendored copies of other libraries are what vulnerability scanners most often flag in a slim image. Removing them shrinks the attack surface. (`-y` answers the confirmation.)

```dockerfile
RUN useradd --system --uid 10001 --no-create-home app
USER app
```
Create a system user with a fixed numeric id and no home folder, and run everything after, including the container's process, as that user. A process that is not root cannot write system files or bind low ports, so a compromise of the app is contained. A numeric id lets Kubernetes policies check "non-root" without reading `/etc/passwd`.

```dockerfile
EXPOSE 3000
```
Documentation only: the container listens on 3000. It does not publish the port (Compose does).

```dockerfile
HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=5 CMD ["oidc-login-health"]
```
Docker runs the command every 15 seconds; exit 0 = healthy. `--start-period=30s` gives start-up time before failures count; five consecutive failures mark the container `unhealthy`. `oidc-login-health` is the project's own command (`tech/python.md`) that GETs `/healthz`: **liveness** only ("the app is up"), so a container is not marked unhealthy just because Keycloak is restarting. The separate `/readyz` route also checks the provider. No `curl` is needed in the image.

```dockerfile
CMD ["gunicorn", "-c", "python:oidc_login.interfaces.gunicorn_conf", "oidc_login.interfaces.wsgi:build_app()"]
```
The **exec form** (a JSON list) runs gunicorn directly as process 1. A string form would start `/bin/sh -c ...` and the shell would receive `SIGTERM` instead of gunicorn, breaking graceful shutdown.

### What the Dockerfile does *not* contain

No password, key or token. Check: `grep -iE "password|secret|token" Dockerfile` prints nothing. Secrets arrive at run time as environment variables from Compose (`env_file: .env`).

### `.dockerignore`

```
.git
.venv
.env
.env.*
!.env.example
...
tests
docs
```
Files named here are not sent to the build context, so they can never be `COPY`'d into an image by mistake. `.env` holds the local passwords; excluding `.env.*` but re-including `!.env.example` keeps secrets out and the example in.

### Run-time hardening (in `docker-compose.yml`)

`read_only: true` (the container's file system cannot be written, except the `tmpfs` at `/tmp`), `cap_drop: [ALL]` (no Linux capabilities), `security_opt: ["no-new-privileges:true"]` (a process cannot gain privileges), the published port bound to `127.0.0.1` on the host.

### `.dockerignore`, line by line

Docker sends the project folder to the engine (the "build context") before building. `.dockerignore` lists what to leave out, so nothing in the list can be copied into an image by accident and the transfer is small.

| Line | Why it is excluded |
| --- | --- |
| `.git` | The history (and anything ever committed). |
| `.venv` | The local Python environment; the image builds its own. |
| `.env` and `.env.*` with `!.env.example` | Local secrets. The `!` line puts the example back: it holds no secret. |
| `__pycache__`, `*.egg-info`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.import_linter_cache`, `.omc` | Generated caches and tool folders. |
| `tests`, `docs`, `logs`, `.github` | Not needed to run the service. |

The Dockerfile then copies only what it names: the lock file, `pyproject.toml`, `README.md` and `src/`. (`idp/` is not excluded because it is not named by any `COPY`.) Both mechanisms apply together: a file must pass the ignore list *and* be named by a `COPY`.

### Line by line: `.dockerignore`

A `.dockerignore` file lists paths left out of the **build context**, the files `docker build` sends to the builder. A smaller context builds faster and cannot leak local secrets into the image.

```text
.git
.venv
```

The git history and the local virtual environment.

```text
.env
.env.*
!.env.example
```

`.env` and every `.env.*` are excluded, but `!.env.example` puts the template back (a leading `!` re-includes a path).

```text
__pycache__
*.egg-info
.pytest_cache
.mypy_cache
.ruff_cache
.import_linter_cache
.omc
```

Python caches, the installed-package metadata folder, the tool caches and the `.omc` work folder.

```text
tests
docs
logs
.github
```

`tests`, `docs`, `logs` and `.github` are not part of the running image.

### Line by line: `Dockerfile`

```dockerfile
# The app as an image: pinned base, hash-checked dependencies, non-root user, read-only friendly.
#   docker compose --profile app up -d --wait app      (starts Keycloak first)
```

The comment: the app as an image with a pinned base, hash-checked dependencies, a non-root user and a read-only-friendly layout; the start command with the compose profile.

```dockerfile
FROM python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753
```

`FROM` starts from the `python:3.12-slim-bookworm` image, pinned by digest (`@sha256:...`), so the build always starts from the same content, not from "whatever is newest".

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
```

`ENV` sets environment variables: no `.pyc` files, unbuffered output (logs appear at once), no pip download cache in the image, and no pip version check over the network.

```dockerfile
WORKDIR /app
```

`WORKDIR /app` sets and creates the working folder.

```dockerfile
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
```

The lock file is copied first, then `pip install --require-hashes -r requirements.lock` installs from it: pip refuses any file whose hash is not listed. Copying the lock before the source means this slow layer is reused when only the code changes.

```dockerfile
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .
```

The project metadata and `src` are copied and the project is installed with `--no-deps` (all dependencies are already installed from the lock).

```dockerfile
# The packaging tools are not needed to run the service, and their vendored libraries are what vulnerability
# scanners most often flag in a slim image: remove them.
RUN pip uninstall -y pip setuptools
```

The packaging tools `pip` and `setuptools` are removed after use: not needed at run time, and the libraries bundled inside them are what vulnerability scanners flag most in a slim image.

```dockerfile
RUN useradd --system --uid 10001 --no-create-home app
USER app
```

`useradd --system --uid 10001 --no-create-home app` creates an unprivileged account and `USER app` runs everything after, and the container, as it. A compromised process then has no root powers.

```dockerfile
EXPOSE 3000
```

`EXPOSE 3000` documents the port.

```dockerfile
HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=5 CMD ["oidc-login-health"]
```

`HEALTHCHECK` runs the health program every 15 seconds (10-second limit, ignoring failures for the first 30 seconds, unhealthy after 5 failures).

```dockerfile
CMD ["gunicorn", "-c", "python:oidc_login.interfaces.gunicorn_conf", "oidc_login.interfaces.wsgi:build_app()"]
```

`CMD` runs gunicorn with the configuration module and the app factory. The list form runs the program directly, without a shell.

## Try it yourself

(Needs Docker running with free disk space.)

1. Build:
   ```bash
   make docker-build
   ```
   Expect `naming to docker.io/library/security-oauth-login-done-right:dev` at the end.
2. Inspect the layers:
   ```bash
   docker history security-oauth-login-done-right:dev | head
   ```
   Expect one row per instruction, with sizes; the lock install is the largest.
3. Check the user and that pip is gone:
   ```bash
   docker run --rm --entrypoint sh security-oauth-login-done-right:dev -c 'id; python -m pip --version'
   ```
   Expect `uid=10001(app)` and `No module named pip`.
4. Run it next to Keycloak (`make up` first) and watch the health state:
   ```bash
   make docker-run && docker compose ps
   ```
   Expect the `app` service `(healthy)`. Then `make down`.

(In the author's verification this image built and started and the container reported healthy; these four commands were not re-run when this note was written because the Docker engine's disk was full that night. Treat the expected outputs as what the Dockerfile above produces. If port 3000 is busy on your machine, set `APP_PORT` in `.env`.)

## Mistakes people make

- `FROM python:latest`: a moving target. Pin by digest.
- Running as root in the container.
- Copying the whole folder, `.env` included. `.dockerignore` and the narrow `COPY` lines prevent it.
- Putting secrets in `ENV` or `RUN`: they stay in the image history forever.
- Shell-form `CMD`, which breaks signal handling.
- Installing dependencies after copying the source, which busts the cache on every code change.
- Leaving build tools in the final image.

## Check yourself

1. Image versus container?
   *An image is a read-only template; a container is a running instance of it.*
2. Why `@sha256:` after the tag?
   *A tag can be moved; a digest identifies exact content.*
3. Why the exec form of `CMD`?
   *Gunicorn becomes process 1 and receives `SIGTERM` directly.*
4. Why copy `requirements.lock` before `src`?
   *The dependency layer stays cached until the lock changes.*
5. What does `USER app` accomplish?
   *The container's processes run without root privileges.*

## Further reading

- Dockerfile reference: https://docs.docker.com/reference/dockerfile/
- Best practices for building images: https://docs.docker.com/build/building/best-practices/
- Python official image: https://hub.docker.com/_/python
- Docker security: https://docs.docker.com/engine/security/
