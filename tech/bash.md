# Bash

## What it is

Bash is a **shell**: a program that reads a line of text, runs the command it names, and shows the result. It is also a small programming language. This repository has no script file of its own; Bash appears as the **shell fragments** inside the `Makefile` recipes (each recipe line is run by the system shell, `/bin/sh`), and inside the Keycloak container's health check, which relies on a Bash feature.

Terms: a **process** is a running program; an **exit code** is the number a process returns when it ends (0 = success, anything else = failure); **standard input / output / error** (stdin, stdout, stderr) are the three streams every process has; a **pipe** `a | b` connects a's output to b's input; a **file descriptor** is a small number naming an open stream (0 stdin, 1 stdout, 2 stderr, and any you open yourself).

## Why this repository uses it

Small glue jobs: create `.env` once, check that the identity provider answers, decide whether Keycloak is healthy. These are one-liners where a separate script file would be heavier than the job.

## Where it appears

| Path | What it does with Bash |
| --- | --- |
| `Makefile` target `env` | `[ -f .env ] \|\| { cp ...; echo ...; }`: create `.env` from the example once. |
| `Makefile` variable `PYTHON` | `command -v python3.13 \|\| command -v python3.12 \|\| command -v python3`: pick an interpreter. |
| `Makefile` target `idp-check` | `curl ... \| python -c ...`: pipes. |
| `docker-compose.yml` (Keycloak `healthcheck`) | `exec 3<>/dev/tcp/127.0.0.1/9000 && printf ... >&3 && grep ... <&3`: an HTTP request written by hand. |
| `.github/workflows/ci.yml` | Each `run:` line is run by Bash on the CI machine. |

## How it works underneath

1. Bash splits a line into **words**: the first is the command, the rest are arguments. It finds the program in the folders listed in `PATH`, starts a process for it, waits, and stores the exit code in `$?`.
2. `a && b` runs `b` only if `a` succeeded (exit 0). `a || b` runs `b` only if `a` failed. `{ ...; }` groups several commands.
3. `[ -f .env ]` is the `test` command: exit 0 if the file exists.
4. A **redirect** changes where a stream goes: `> file` (stdout to a file), `< file` (stdin from a file), `2>&1` (stderr to wherever stdout goes), `>&3` (stdout to descriptor 3), `<&3` (stdin from descriptor 3).
5. `exec 3<>/dev/tcp/HOST/PORT` is special to Bash: it opens a TCP connection and makes it descriptor 3, open for reading and writing (`<>`). `/dev/tcp/...` does not exist as a file; Bash itself intercepts the name. It is a Bash feature, not part of every shell.
6. `$( ... )` runs a command and substitutes its output.

### Ideas you need first

- **A terminal and a shell.** A terminal is a window where you type text commands instead of clicking. The program that reads what you type is the shell; Bash is one shell. You type a line, press Enter, and the shell runs it.
- **A command, its arguments and its flags.** A command is the name of a program (`ls`, `make`, `docker`). What follows are **arguments**: extra words that tell it what to work on. A **flag** (or option) is an argument that starts with `-` or `--` and changes how the command behaves, such as `-l` or `--help`.
- **A directory, a path and the working directory.** A directory is a folder. A path names a file by listing the folders to open: `scripts/demo.sh` means "the file `demo.sh` inside the folder `scripts`". The **working directory** is the folder you are "in"; relative paths are read from there. `.` means "this folder", `..` means "the folder above".
- **`PATH`.** An environment variable holding a list of folders. When you type `gunicorn`, the shell looks through those folders, in order, for a program with that name. A path with a slash (`.venv/bin/gunicorn`) names the program directly and skips the search.
- **An environment variable.** A named piece of text given to a process when it starts. `NAME=value command` sets one for a single command; `export NAME=value` sets it for the shell and every program it starts afterwards.
- **A process and its exit code.** Running a command starts a process. When it ends it returns a number: 0 means success, anything else means failure. The shell stores the last one in `$?`.
- **Standard input, output and error.** Every process has three text streams: input it reads (stdin, 0), normal output (stdout, 1) and error output (stderr, 2). A **redirect** sends one somewhere else: `> file` writes stdout to a file, `2> file` writes stderr, `2>&1` sends stderr to wherever stdout goes, `< file` reads stdin from a file. `/dev/null` is a special file that throws away whatever is written to it.
- **A pipe.** `a | b` connects a's stdout to b's stdin, so b reads what a prints. Both run at the same time.
- **A file descriptor.** The number the operating system gives to an open stream. 0, 1 and 2 are the three standard ones; you can open more (`exec 3<>...` below).
- **A background process and a signal.** A trailing `&` starts a command without waiting for it. A **signal** is a message the operating system sends to a process; `SIGTERM` means "please stop", and a well-written program cleans up and exits when it gets one.
- **A variable and quoting.** `NAME=value` sets a shell variable; `$NAME` reads it. Double quotes (`"$NAME"`) keep a value with spaces as one word. Single quotes (`'...'`) pass the text exactly as written. `$(command)` runs a command and substitutes its output.
- **A script and the shebang.** A script is a text file of commands. Its first line, `#!/usr/bin/env bash`, tells the operating system which program should run the file. The file must be marked executable (`chmod +x`).

## Walkthrough of this repository's use

### Create `.env` once

```make
env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
```
Read it as: "if `.env` exists, stop (success); otherwise copy the example and say so." `[ -f .env ]` succeeds when the file exists, so `||` skips the right side. When it does not exist, `[` fails, so `||` runs the group: `cp` copies the example, `echo` prints a message. The leading `@` is Make's: do not print the command. Existing `.env` files are never overwritten, so your edits are safe.

### Pick an interpreter

```make
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
```
`command -v NAME` prints the path of `NAME` if it exists and fails otherwise, so the `||` chain tries 3.13, then 3.12, then plain `python3`, and `$(shell ...)` (a Make function) captures the first path found.

### Pipes with `curl`

```make
@curl -fsS $(OIDC_ISSUER)/.well-known/openid-configuration | $(PY) -c "import json,sys; d=json.load(sys.stdin); print('issuer                ', d['issuer']); ..."
```
`curl` writes the JSON document to its stdout; the pipe connects that to the Python program's stdin, where `json.load(sys.stdin)` reads it. `-c "..."` gives Python the program as text. The double quotes protect the semicolons and brackets from the shell; the single quotes inside are Python's. (Flags: `tech/curl.md`.) The Make variable `$(OIDC_ISSUER)` is expanded by Make before the shell sees the line.

### Keycloak's health check: an HTTP request by hand

```yaml
test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/9000 && printf 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3 && grep -q '\"status\": \"UP\"' <&3"]
```
The Keycloak image has no `curl`, but its shell is Bash, so this does the job with built-ins. Step by step:
1. `exec 3<>/dev/tcp/127.0.0.1/9000`: open a TCP connection to Keycloak's management port 9000 as descriptor 3. If nothing is listening yet, this fails and the check reports "not healthy".
2. `&&`: continue only if that worked.
3. `printf '...' >&3`: write a complete HTTP request into the connection. `\r\n` is a carriage return and line feed (HTTP's line ending); a blank line (`\r\n\r\n`) ends the headers. `Connection: close` asks the server to hang up after replying.
4. `grep -q '"status": "UP"' <&3`: read the reply from descriptor 3 and succeed (exit 0) if it contains `"status": "UP"`. `-q` means "quiet: just set the exit status".

The YAML doubles the backslashes and escapes the quotes (`tech/yaml.md`) so the shell receives exactly the text above. Docker treats exit 0 as healthy.

## Try it yourself

1. Watch `||` and the `[ -f ]` test:
   ```bash
   bash -c '[ -f /nonexistent ] || { echo "created"; }'
   ```
   Expect `created`.
2. Try the interpreter chain:
   ```bash
   command -v python3.99 || command -v python3
   ```
   Expect the path of your `python3` (the first command prints nothing and fails).
3. See `/dev/tcp` fail cleanly when nothing listens:
   ```bash
   bash -c 'exec 3<>/dev/tcp/127.0.0.1/9'; echo "exit $?"
   ```
   Expect `Connection refused` and `exit 1`.
4. See what the Makefile would run without running it:
   ```bash
   make -n env
   ```
   Expect the `[ -f .env ] || { cp ...; }` line printed.
5. With Keycloak up (`make up`), repeat the health check by hand, inside the container (port 9000 is not published to your machine):
   ```bash
   docker compose exec keycloak bash -c "exec 3<>/dev/tcp/127.0.0.1/9000 && printf 'GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3 && cat <&3"
   ```
   Expect an HTTP reply ending in a small JSON body with `"status": "UP"`. (This needs Docker; it was not re-run when this note was written, because the Docker engine's disk was full that night.)

## Mistakes people make

- Forgetting quotes: `echo $x` breaks on spaces; quote variables.
- Using `[ -f $file ]` with an empty variable, which changes the meaning; quote it.
- Assuming `/dev/tcp` works in every shell. It is Bash-only; in `dash` (Debian's `sh`) it does not exist.
- Reading `$?` after another command ran.
- Hiding failures with `|| true` everywhere. The recipes here do not.
- Writing `$VAR` inside a Makefile when the shell should expand it: Make needs `$$VAR` (the Makefile has no such case; the Compose file uses the same trick).

## Check yourself

1. What does `[ -f .env ] || { cp .env.example .env; }` do when `.env` exists?
   *Nothing: the test succeeds, so the right side is skipped.*
2. What does `curl ... | python -c ...` connect?
   *curl's stdout to Python's stdin.*
3. What does `exec 3<>/dev/tcp/HOST/PORT` do?
   *Opens a TCP connection as file descriptor 3, readable and writable.*
4. Why is `command -v` used in the Makefile?
   *To find which of several Python interpreters exists.*
5. What exit code means success?
   *0.*

## Further reading

- GNU Bash manual (this machine runs Bash 5.3): https://www.gnu.org/software/bash/manual/bash.html
- Redirections (including `/dev/tcp`): https://www.gnu.org/software/bash/manual/bash.html#Redirections
- Conditional expressions (`[ -f ]`): https://www.gnu.org/software/bash/manual/bash.html#Bash-Conditional-Expressions
