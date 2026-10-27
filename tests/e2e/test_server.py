"""A real server process, a scripted browser and Keycloak: sign-in, session, refresh, sign-out, SIGTERM."""

import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

import httpx
import pytest

from oidc_login.interfaces.scripted_browser import ProviderBrowser

pytestmark = pytest.mark.e2e
STARTUP_SECONDS = 180
SERVE = [
    sys.executable,
    "-m",
    "gunicorn",
    "-c",
    "python:oidc_login.interfaces.gunicorn_conf",
    "oidc_login.interfaces.wsgi:build_app()",
]
SESSION = "__Host-session"
LOGIN = "__Host-login"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _environment(port: int, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "APP_ENV": "development",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "OIDC_REDIRECT_URI": f"http://localhost:{port}/callback",
        }
    )
    env.update(extra)
    return env


def _wait_until_ready(port: int, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        assert server.poll() is None, "the server exited before it was ready"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise AssertionError(f"the server did not become ready in {STARTUP_SECONDS} seconds")


@pytest.fixture
def server():
    """The app on the port its redirect URI is registered for, as production starts it (gunicorn)."""
    port = urlsplit(os.environ["OIDC_REDIRECT_URI"]).port or 3000
    process = subprocess.Popen(
        SERVE,
        env=_environment(port, OIDC_REDIRECT_URI=os.environ["OIDC_REDIRECT_URI"]),
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until_ready(port, process)
        yield port, process
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=60)


def _cookie(response: httpx.Response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}=") and "Max-Age=0" not in header:
            return header.split("=", 1)[1].split(";", 1)[0]
    return None


def test_the_whole_flow_against_a_running_server(server):
    port, _ = server
    app = httpx.Client(base_url=f"http://127.0.0.1:{port}", follow_redirects=False, timeout=60)
    user = ProviderBrowser("demo-user", os.environ["DEMO_USER_PASSWORD"])

    assert app.get("/readyz").status_code == 200  # the server reaches the provider

    start = app.get("/login")
    assert start.status_code == 302
    assert "code_challenge_method=S256" in start.headers["location"]
    login_cookie = _cookie(start, LOGIN)
    assert login_cookie

    hop = user.authorize(start.headers["location"])
    assert hop.location is not None, f"the provider did not redirect back (status {hop.status})"
    target = urlsplit(hop.location)
    callback = app.get(f"{target.path}?{target.query}", headers={"Cookie": f"{LOGIN}={login_cookie}"})
    assert callback.status_code == 302
    session = _cookie(callback, SESSION)
    assert session
    assert "." not in session
    cookie = {"Cookie": f"{SESSION}={session}"}

    assert app.get("/me", headers=cookie).json()["username"] == "demo-user"
    assert app.get("/api/profile", headers=cookie).json()["username"] == "demo-user"
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', app.get("/", headers=cookie).text)
    assert csrf
    assert app.post("/refresh", headers={**cookie, "X-CSRF-Token": csrf.group(1)}).status_code == 200
    assert app.post("/logout", headers=cookie).status_code == 403  # no CSRF token
    assert app.post("/logout", headers=cookie, data={"csrf_token": csrf.group(1)}).status_code == 303
    assert app.get("/me", headers=cookie).status_code == 401
    user.close()
    app.close()


def test_sigterm_shuts_the_server_down_cleanly(server):
    _, process = server
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=60) == 0
    log = process.stderr.read()
    assert "Handling signal: term" in log
    assert "provider client closed" in log
    assert "Shutting down: Master" in log


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"OIDC_CLIENT_SECRET": ""}, "OIDC_CLIENT_SECRET is required"),
        ({"APP_ENV": "production"}, "https in production"),
        ({"OIDC_REDIRECT_URI": "http://app.example.test/callback"}, "only accepted for localhost"),
    ],
)
def test_the_server_refuses_to_start_with_an_unsafe_or_missing_setting(overrides, message):
    result = subprocess.run(
        SERVE,
        env=_environment(_free_port(), **overrides),
        capture_output=True,
        text=True,
        timeout=STARTUP_SECONDS,
        check=False,
    )
    assert result.returncode != 0
    assert message in result.stderr
