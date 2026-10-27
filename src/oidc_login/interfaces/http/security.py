"""Browser-facing defenses: response headers and the two cookies."""

from __future__ import annotations

from werkzeug.wrappers import Response

SESSION_COOKIE = "__Host-session"
LOGIN_COOKIE = "__Host-login"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"

# No script, no frames, forms and styles from this origin only. The provider's login page is a different origin and
# has its own headers.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # The callback URL carries a one-time code; the referrer must never leak it to another site.
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Cache-Control": "no-store",
}


def apply_security_headers(response: Response) -> Response:
    """Add the security headers to every response; a handler's own value wins."""
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def set_cookie(response: Response, name: str, value: str, *, max_age: int, secure: bool) -> None:
    """Set an opaque, HttpOnly, SameSite=Lax cookie. The ``__Host-`` prefix makes browsers insist on Secure,
    ``Path=/`` and no ``Domain``. Lax (not Strict) is needed so the cookie comes back on the provider's redirect."""
    response.set_cookie(name, value, max_age=max_age, httponly=True, secure=secure, samesite="Lax", path="/")


def clear_cookie(response: Response, name: str, *, secure: bool) -> None:
    """Expire a cookie in the browser."""
    response.delete_cookie(name, httponly=True, secure=secure, samesite="Lax", path="/")
