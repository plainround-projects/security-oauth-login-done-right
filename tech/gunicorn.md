# Gunicorn 25

## What it is

Gunicorn ("Green Unicorn") is a **WSGI HTTP server** for Python. A web framework such as Flask knows how to answer a request but does not listen on the network. Gunicorn listens on a port, parses HTTP, hands each request to the Flask app, and writes the response back. It also runs several copies of your app (**workers**) so one slow request does not block everyone, and it restarts workers that die or hang. The pinned version is `gunicorn==25.3.0`.

## Why this repository uses it

The lesson asks for a service that starts, answers, and **shuts down gracefully**: when told to stop, it finishes the requests in flight, then closes its HTTP client to the identity provider. Flask's built-in server is for development only; gunicorn is a production-grade server and lets the repository configure timeouts, request-size limits and shutdown behaviour in one small file.

## Where it appears

| Path | What it does with gunicorn |
| --- | --- |
| `src/oidc_login/interfaces/gunicorn_conf.py` | All settings, written as Python variables. |
| `src/oidc_login/interfaces/wsgi.py` | `build_app()` and `close_all()` used by gunicorn and its exit hook. |
| `Makefile` | `SERVE := .venv/bin/gunicorn -c python:oidc_login.interfaces.gunicorn_conf "oidc_login.interfaces.wsgi:build_app()"` |
| `Dockerfile` | `CMD ["gunicorn", "-c", "python:oidc_login.interfaces.gunicorn_conf", "oidc_login.interfaces.wsgi:build_app()"]` |
| `tests/e2e/test_server.py` | Starts a real server process, checks it, then sends it SIGTERM. |

## How it works underneath

1. You start one **master** process. It reads the config, opens the listening socket once, then **forks** (copies itself into) worker processes.
2. Each worker imports your app by the name you gave: `oidc_login.interfaces.wsgi:build_app()` means "import that module and call `build_app()` to get the WSGI app".
3. All workers accept connections on the shared socket. With worker class `gthread`, each worker also runs a pool of **threads** (here 8), so one worker handles several requests at once. Total concurrency here is 1 worker x 8 threads = 8.
4. The master watches its children. A worker that is silent for more than `timeout` seconds is killed and replaced.
5. A **signal** from the operating system controls the master. `SIGTERM` (the polite stop, sent by `kill` and by `docker stop`) means graceful shutdown: stop accepting, let workers finish, then exit. `SIGINT` (Ctrl-C) does the same.
6. When a worker exits, gunicorn calls the `worker_exit(server, worker)` hook inside it. This repository uses the hook to close the HTTP client that talks to the identity provider.

### Ideas you need first

- **A server and a port.** A server is a program that waits for other programs (clients) to connect and ask for something. It listens on a **port**, a number between 1 and 65535 that identifies one waiting program on a machine; a client connects to an address plus a port, such as `127.0.0.1:3000`. A **socket** is the operating system's handle for one such network connection (or the listening end of one).
- **The address `127.0.0.1` and `0.0.0.0`.** `127.0.0.1` is the machine's own loopback address: only programs on the same machine can reach it. `0.0.0.0` means "listen on every network address of this machine".
- **A process, a fork and a worker.** A process is one running copy of a program. To **fork** is to make a copy of the running process. gunicorn's first process (the **master**) opens the port once and forks **workers**, which do the actual request handling. A worker that crashes or hangs is replaced.
- **A thread.** Inside one process, several threads can work at the same moment and share memory. With `gthread` workers every worker has a small pool of threads, each handling one request at a time.
- **A signal.** A short message from the operating system to a process. `SIGTERM` is the polite request to stop (sent by `kill` and by `docker stop`); `SIGINT` is what Ctrl-C sends; `SIGKILL` cannot be caught and ends the process at once. **Graceful shutdown** means catching `SIGTERM`, finishing the requests already being served, closing resources, then exiting.
- **A timeout.** A limit on how long something may take before it is treated as failed.
- **A hook.** A function you hand to a framework to be called at a fixed moment. gunicorn calls `worker_exit` as each worker exits.

## Walkthrough of this repository's use

```python
bind = f"{os.environ.get('APP_HOST', '127.0.0.1')}:{os.environ.get('APP_PORT', '3000')}"
```
Where to listen. Default is the loopback address `127.0.0.1` (reachable only from the same machine). Inside Docker, Compose sets `APP_HOST: 0.0.0.0` so the container accepts connections, and the published port in `docker-compose.yml` is bound to `127.0.0.1` on the host, so the app is still not reachable from other machines.

```python
workers = 1
threads = 8
worker_class = "gthread"
```
**One** worker process with **eight** threads, on purpose. `gthread` is the threaded worker. The pending logins and the signed-in sessions live in this process's memory (`InMemoryPendingLoginStore`, `InMemorySessionStore`), so a second worker process would have its own, empty copies: a user signed in on one worker would look signed out on the other, and a login started on one could not be completed on the other. Threads share memory, so eight threads give concurrency without that problem, and the stores guard themselves with locks. The price: a restart signs everyone out, and scaling out needs a shared store such as Redis behind the same ports (`ARCHITECTURE.md`).

```python
timeout = 30
graceful_timeout = 20
keepalive = 5
```
`timeout`: a worker that sends no heartbeat for 30 seconds is killed. `graceful_timeout`: after a stop signal, workers have 20 seconds to finish in-flight requests before being force-killed. `keepalive`: how long (seconds) an idle connection is kept open for another request.

```python
control_socket_disable = True  # no admin socket in the home directory: one fewer local attack surface
```
Gunicorn 25.1 added a **control socket** (a local file that the `gunicornc` tool uses to manage a running server). Turning it off means no extra file and no extra way to talk to the server.

```python
limit_request_line = 4094
limit_request_fields = 50
```
Refuse a request whose first line (method, path, version) is over 4094 bytes, or that has more than 50 header lines. These are denial-of-service guardrails (the gunicorn default for headers is 100).

```python
accesslog = None
errorlog = "-"
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "oidc_login.infrastructure.logging.JsonFormatter"}},
    "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stderr"}},
    "root": {"level": "INFO", "handlers": ["stderr"]},
    "loggers": {"gunicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False}},
}
```
`accesslog = None`: gunicorn writes no access log, because the application writes one structured line per request (with a request id, status and duration, and without the cookie or body). `errorlog = "-"` means "standard error". `logconfig_dict` is Python's `logging.config.dictConfig` format: it routes both the app's loggers and gunicorn's own messages through the repository's `JsonFormatter`, so every line is JSON. The `"()"` key means "create this formatter by calling this class". A `root` entry is required: without it dictConfig fails with "Unable to configure root logger" (a mistake made and fixed while building this).

```python
def worker_exit(server: object, worker: object) -> None:
    from oidc_login.interfaces.wsgi import close_all
    close_all()
```
Runs in each worker as it exits. `close_all()` closes the HTTP client of every app the process built and logs `provider client closed`. The import is inside the function so the module is only loaded in a worker that actually built an app.

### How the app is named

`-c python:oidc_login.interfaces.gunicorn_conf` loads the configuration from an importable Python module instead of a file path (`python:` prefix). `"oidc_login.interfaces.wsgi:build_app()"` is the **application factory** form: gunicorn calls `build_app()` in each worker. `build_app()` reads `Settings.from_environment(os.environ)` first, so a missing `NOTES_DB_PASSWORD` stops the worker at start-up with a clear error rather than after serving traffic.

### Line by line: `src/oidc_login/interfaces/gunicorn_conf.py`

```python
"""gunicorn settings.

Start with ``gunicorn -c python:oidc_login.interfaces.gunicorn_conf "oidc_login.interfaces.wsgi:build_app()"``.

One worker with several threads: sessions and pending logins live in this process's memory (see ARCHITECTURE.md).
SIGTERM makes the master stop accepting connections and lets in-flight requests finish (up to ``graceful_timeout``)
before the worker closes its HTTP client in ``worker_exit``.
"""
```

The docstring: the start command, and the reason for a single worker: sessions and pending logins live in this process's memory, so a second worker would not know about them. SIGTERM (the polite stop signal) makes the master stop accepting connections and lets running requests finish for up to `graceful_timeout` seconds before the worker closes its HTTP client in `worker_exit`.

```python
from __future__ import annotations

import os
from typing import Any
```

Type hints kept as text, `os` and `Any`. In a gunicorn configuration file each module-level variable is one setting.

```python
bind = f"{os.environ.get('APP_HOST', '127.0.0.1')}:{os.environ.get('APP_PORT', '3000')}"
```

`bind` is the address and port to listen on, from `APP_HOST` and `APP_PORT`, default `127.0.0.1:3000`.

```python
workers = 1
threads = 8
worker_class = "gthread"
```

`workers = 1`: one worker **process**. `threads = 8` with `worker_class = "gthread"`: eight **threads** (lightweight lines of execution inside the process) to serve requests at the same time.

```python
timeout = 30
```

`timeout = 30`: a worker silent for 30 seconds is killed and restarted.

```python
graceful_timeout = 20
```

`graceful_timeout = 20`: after a stop signal, workers get 20 seconds to finish.

```python
keepalive = 5
```

`keepalive = 5`: wait five seconds for another request on an open connection.

```python
control_socket_disable = True
```

`control_socket_disable = True` turns off gunicorn's local control socket.

```python
limit_request_line = 4094
limit_request_fields = 50
```

`limit_request_line = 4094` and `limit_request_fields = 50` cap the first line of a request and the number of headers.

```python
accesslog = None  # the application writes one structured line per request
errorlog = "-"
```

`accesslog = None` (the application writes one structured line per request) and `errorlog = "-"` (standard error).

```python
logconfig_dict: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "oidc_login.infrastructure.logging.JsonFormatter"}},
    "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stderr"}},
    "root": {"level": "INFO", "handlers": ["stderr"]},
    "loggers": {"gunicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False}},
}
```

`logconfig_dict` is a Python logging configuration: version 1; keep other loggers; a formatter built by calling the `JsonFormatter` class (the `"()"` key); a handler writing to standard error (`ext://sys.stderr` names the real stream); the root at `INFO`; and `gunicorn.error` using the same handler and not passing messages up, so each appears once as JSON.

```python
def worker_exit(server: object, worker: object) -> None:
    """Called in the worker as it exits: close the provider's HTTP client."""
    from oidc_login.interfaces.wsgi import close_all

    close_all()
```

`worker_exit` is a **hook** gunicorn calls in the worker as it exits; it imports `close_all` inside the function and closes the provider's HTTP client.

## Try it yourself

1. Check the version and your settings load:
   ```bash
   .venv/bin/gunicorn --version
   .venv/bin/python -c "import oidc_login.interfaces.gunicorn_conf as c; print(c.bind, c.workers, c.threads, c.worker_class)"
   ```
   Expect `gunicorn (version 25.3.0)` and `127.0.0.1:3000 1 8 gthread`.
2. Start it (needs `make up`) and stop it politely:
   ```bash
   make run   # in terminal 1; press Ctrl-C when you want it to stop
   ```
   Expect JSON log lines, then on Ctrl-C a `Handling signal: int` line, `provider client closed`, and `Shutting down: Master`.
3. Run the shutdown proof (needs `make up`):
   ```bash
   make test-e2e
   ```
   Expect all tests to pass. `test_sigterm_shuts_the_server_down_cleanly` starts a real gunicorn, sends SIGTERM, requires exit code 0, and finds `Handling signal: term`, `provider client closed` and `Shutting down: Master` in the server's log.
4. Ask the server for its health (while it runs):
   ```bash
   make health
   ```
   Expect `healthy`.

## Mistakes people make

- Running the development server in production.
- Binding `0.0.0.0` on a laptop and exposing the app to the whole network. Here the default is `127.0.0.1`.
- Keeping state in process memory when there are several workers (each sees different data). This repository does keep it in memory, and so runs exactly one worker.
- Setting `timeout` very high "to fix slow requests", which hides hung workers. Thirty seconds is kept.
- Killing with `SIGKILL` (`kill -9`): nothing gets cleaned up. Use `SIGTERM`.
- A log format that differs between gunicorn and the app, which makes logs hard to search. One `JsonFormatter` serves both.

## Check yourself

1. What is the difference between a worker and a thread here?
   *A worker is a separate process; each worker runs four threads that share its memory.*
2. What does `SIGTERM` make gunicorn do?
   *Stop accepting connections, let workers finish in-flight requests (up to `graceful_timeout`), then exit.*
3. Why is there exactly one worker process?
   *Sessions and pending logins are in process memory; a second process would not see them.*
4. What does `build_app()` do at the end of its call?
   *Returns the Flask app; before that it validates settings, configures logging and wires the adapters (the provider is contacted later, on first use).*
5. What is `worker_exit` used for here?
   *Closing the worker's HTTP client to the provider during shutdown.*

## Further reading

- Gunicorn 25 documentation: https://gunicorn.org/
- Settings reference: https://gunicorn.org/reference/settings/
- Signal handling: https://gunicorn.org/signals/
- Python `logging.config.dictConfig`: https://docs.python.org/3.12/library/logging.config.html#logging-config-dictschema
