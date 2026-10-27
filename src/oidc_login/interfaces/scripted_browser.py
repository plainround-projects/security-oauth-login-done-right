"""A scripted browser for the demo and the tests: it plays the user at the provider's login page and at the app.

It is deliberately small. The provider's login page is a form; this fills it in and reports where the provider
redirects. Nothing here is reachable from the running app.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx
from flask import Flask
from werkzeug.test import TestResponse


@dataclass(frozen=True, slots=True)
class Hop:
    """One response from the provider: its status, the ``Location`` it redirects to (if any) and the body."""

    status: int
    location: str | None
    body: str


class _LoginForm(HTMLParser):
    """Finds the sign-in form in the provider's page: its action URL and its hidden fields."""

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and (
            values.get("id") == "kc-form-login" or "login-actions/authenticate" in (values.get("action") or "")
        ):
            self.action, self._inside = values.get("action"), True
        elif tag == "input" and self._inside and values.get("type") == "hidden" and values.get("name"):
            self.fields[str(values["name"])] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._inside = False


class ProviderBrowser:
    """The user's browser at the identity provider: keeps the provider's cookies, fills in the login form.

    Cookies are kept by hand: the provider marks some of them ``Secure`` even on ``http://localhost``, which a real
    browser accepts (localhost counts as secure) but a plain HTTP client's cookie jar rightly drops.
    """

    def __init__(self, username: str, password: str, timeout_seconds: float = 300) -> None:
        self._username = username
        self._password = password
        self._http = httpx.Client(follow_redirects=False, timeout=timeout_seconds)
        self._cookies: dict[str, str] = {}

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    def _send(self, method: str, url: str, data: dict[str, str] | None = None) -> httpx.Response:
        headers = (
            {"Cookie": "; ".join(f"{name}={value}" for name, value in self._cookies.items())} if self._cookies else {}
        )
        response = self._http.request(method, url, data=data, headers=headers)
        for header in response.headers.get_list("set-cookie"):
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            if "Max-Age=0" in header or value in {"", '""'}:
                self._cookies.pop(name, None)
            else:
                self._cookies[name] = value
        return response

    def authorize(self, authorization_url: str) -> Hop:
        """Open the authorization URL. At the login page, sign in; return the provider's final answer for this
        request (normally a redirect back to the app, or an error page)."""
        first = self._send("GET", authorization_url)
        if first.status_code in {301, 302, 303}:
            return Hop(first.status_code, first.headers.get("location"), first.text)
        form = _LoginForm()
        form.feed(first.text)
        if first.status_code != 200 or not form.action:
            return Hop(first.status_code, None, first.text)
        data = {**form.fields, "username": self._username, "password": self._password}
        second = self._send("POST", form.action, data)
        return Hop(second.status_code, second.headers.get("location"), second.text)


class AppBrowser:
    """The user's browser at the app, over the Flask test client, on https://localhost so the Secure cookie travels."""

    def __init__(self, app: Flask) -> None:
        self.client = app.test_client()

    def request(self, method: str, path: str, **kwargs: Any) -> TestResponse:
        """Send a request to the app."""
        kwargs.setdefault("base_url", "https://localhost")
        return self.client.open(path, method=method, **kwargs)

    def get(self, path: str, **kwargs: Any) -> TestResponse:
        """GET a path."""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> TestResponse:
        """POST to a path."""
        return self.request("POST", path, **kwargs)

    def cookie(self, name: str) -> str | None:
        """The value of one of the app's cookies, if the browser holds it."""
        found = self.client.get_cookie(name, domain="localhost")
        return None if found is None else found.value

    def follow_callback(self, location: str) -> TestResponse:
        """Do what the browser does after the provider redirects: GET the callback path and query on the app."""
        target = urlsplit(location)
        return self.get(f"{target.path}?{target.query}")

    def sign_in(self, provider: ProviderBrowser, scope: str | None = None) -> TestResponse:
        """A complete sign-in: start at the app, authenticate at the provider, come back to the callback."""
        start = self.get("/login" + (f"?scope={scope}" if scope else ""))
        hop = provider.authorize(start.headers["Location"])
        if hop.location is None:
            raise AssertionError(f"the provider did not redirect back (status {hop.status})")
        return self.follow_callback(hop.location)
