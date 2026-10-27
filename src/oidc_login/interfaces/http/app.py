"""The Flask application factory. Routes translate HTTP to flow calls and back; no rule lives here."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from flask import Flask, Response, g, jsonify, make_response, redirect, render_template, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from oidc_login.domain import scopes
from oidc_login.domain.errors import (
    InsufficientScopeError,
    LoginError,
    ProviderError,
    ProviderUnavailableError,
    SessionNotFoundError,
    StateMismatchError,
    TokenValidationError,
)
from oidc_login.domain.models import UserSession
from oidc_login.interfaces.composition import Container
from oidc_login.interfaces.http.security import (
    CSRF_FIELD,
    CSRF_HEADER,
    LOGIN_COOKIE,
    SESSION_COOKIE,
    apply_security_headers,
    clear_cookie,
    set_cookie,
)

_log = logging.getLogger("oidc_login.http")
_PUBLIC = frozenset({"healthz", "readyz", "static"})
REPORTS_SCOPE = "reports:read"


def create_app(container: Container) -> Flask:
    """Build the application around a wired container."""
    settings = container.settings
    flow = container.flow
    secure = settings.cookie_secure
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    if settings.trusted_proxy_count:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app, x_for=settings.trusted_proxy_count, x_proto=settings.trusted_proxy_count
        )

    @app.before_request
    def load_session() -> None:
        g.started = time.perf_counter()
        g.request_id = uuid.uuid4().hex
        g.session = None if request.endpoint in _PUBLIC else flow.resolve(request.cookies.get(SESSION_COOKIE))

    @app.after_request
    def finish(response: Response) -> Response:
        apply_security_headers(response)
        _log.info(
            "request",
            extra={
                "request_id": g.get("request_id"),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - g.get("started", time.perf_counter())) * 1000, 1),
                "subject": g.session.identity.subject if g.get("session") else None,
            },
        )
        return response

    @app.context_processor
    def template_context() -> dict[str, Any]:
        session: UserSession | None = g.get("session")
        return {"session": session, "csrf_token": session.csrf_token if session else ""}

    @app.get("/healthz")
    def healthz() -> ResponseReturnValue:
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz() -> ResponseReturnValue:
        try:
            container.provider.metadata()
        except ProviderUnavailableError as error:
            return jsonify(status="identity provider unavailable", reason=str(error)), 503
        return jsonify(status="ready")

    @app.get("/")
    def home() -> ResponseReturnValue:
        return render_template(
            "home.html", extra_scope=REPORTS_SCOPE, reports_allowed=REPORTS_SCOPE in settings.allowed_extra_scopes
        )

    @app.get("/login")
    def login() -> ResponseReturnValue:
        started = flow.start(request.args.getlist("scope"))
        response = redirect(started.authorization_url, code=302)
        set_cookie(response, LOGIN_COOKIE, started.attempt_id, max_age=started.max_age_seconds, secure=secure)
        return response

    @app.get("/callback")
    def callback() -> ResponseReturnValue:
        if request.args.get("error"):
            _log.warning(
                "provider returned an error",
                extra={"event": "login.rejected", "reason": "provider_error", "error": request.args.get("error")},
            )
            return _failed(400, "Sign-in was not completed.", secure)
        try:
            issued = flow.complete(
                attempt_id=request.cookies.get(LOGIN_COOKIE),
                state=request.args.get("state"),
                code=request.args.get("code"),
            )
        except StateMismatchError as error:
            _log.warning(
                "callback rejected", extra={"event": "login.rejected", "reason": "state", "detail": str(error)}
            )
            return _failed(400, "This sign-in attempt is not valid. Start again.", secure)
        except TokenValidationError as error:
            _log.warning("ID token rejected", extra={"event": "login.rejected", "reason": error.reason})
            return _failed(401, "The identity provider's response could not be verified.", secure)
        except ProviderError as error:
            _log.warning("code exchange refused", extra={"event": "login.rejected", "reason": error.code})
            return _failed(400, "The identity provider refused the sign-in.", secure)
        except ProviderUnavailableError:
            return _failed(502, "The identity provider is not reachable. Try again shortly.", secure)
        response = redirect("/", code=302)
        set_cookie(response, SESSION_COOKIE, issued.raw_session_id, max_age=issued.max_age_seconds, secure=secure)
        clear_cookie(response, LOGIN_COOKIE, secure=secure)
        return response

    @app.post("/logout")
    def logout() -> ResponseReturnValue:
        session = _session()
        if session is not None:
            _require_csrf(session)
            revoked = flow.sign_out(request.cookies.get(SESSION_COOKIE))
            _log.info("logout", extra={"event": "logout", "revoked": revoked})
        response = redirect("/", code=303)
        clear_cookie(response, SESSION_COOKIE, secure=secure)
        return response

    @app.get("/me")
    def me() -> ResponseReturnValue:
        session = _require_session()
        return jsonify(
            subject=session.identity.subject,
            username=session.identity.username,
            scopes=sorted(session.scopes),
            session_expires_at=session.expires_at.isoformat(),
        )

    @app.get("/api/profile")
    def profile() -> ResponseReturnValue:
        session = _require_session()
        access_token, _ = flow.access_token(session)
        info = container.provider.userinfo(access_token)
        return jsonify(subject=info.get("sub"), username=info.get("preferred_username"), email=info.get("email"))

    @app.post("/refresh")
    def refresh() -> ResponseReturnValue:
        session = _require_session()
        _require_csrf(session)
        renewed = flow.refresh(session)
        remaining = int((renewed.tokens.access_expires_at - renewed.last_seen_at).total_seconds())
        return jsonify(refreshed=True, access_token_valid_for_seconds=remaining)

    @app.get("/reports")
    def reports() -> ResponseReturnValue:
        session = _require_session()
        scopes.require(session.scopes, REPORTS_SCOPE)
        return jsonify(report="quarterly summary (sample data)")

    _register_errors(app)
    return app


class _UnauthenticatedError(Exception):
    """No live session on a route that needs one."""


class _CsrfRejectedError(Exception):
    """A state-changing request without the session's CSRF token."""


def _session() -> UserSession | None:
    session: UserSession | None = g.get("session")
    return session


def _require_session() -> UserSession:
    session = _session()
    if session is None:
        raise _UnauthenticatedError
    return session


def _require_csrf(session: UserSession) -> None:
    supplied = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD)
    if supplied is None or not _csrf_matches(session, supplied):
        raise _CsrfRejectedError


def _csrf_matches(session: UserSession, supplied: str) -> bool:
    import hmac

    return hmac.compare_digest(session.csrf_token.encode(), supplied.encode())


def _failed(status: int, message: str, secure: bool) -> Response:
    """A generic failure page; the specific reason is in the log, not in the response. The login-attempt cookie
    is cleared because the attempt is over either way."""
    response = make_response(render_template("error.html", title="Sign-in failed", message=message), status)
    clear_cookie(response, LOGIN_COOKIE, secure=secure)
    return response


def _register_errors(app: Flask) -> None:
    @app.errorhandler(_UnauthenticatedError)
    def unauthenticated(_: _UnauthenticatedError) -> ResponseReturnValue:
        return jsonify(error="unauthenticated", message="Sign in first"), 401

    @app.errorhandler(_CsrfRejectedError)
    def csrf_rejected(_: _CsrfRejectedError) -> ResponseReturnValue:
        return jsonify(error="csrf_rejected", message="Missing or wrong CSRF token"), 403

    @app.errorhandler(InsufficientScopeError)
    def insufficient_scope(error: InsufficientScopeError) -> ResponseReturnValue:
        _log.warning("scope check refused", extra={"event": "authz.refused", "needed": error.scope})
        return jsonify(error="insufficient_scope", message=f"This route needs the {error.scope} scope"), 403

    @app.errorhandler(SessionNotFoundError)
    def session_gone(_: SessionNotFoundError) -> ResponseReturnValue:
        return jsonify(error="unauthenticated", message="Your session ended. Sign in again."), 401

    @app.errorhandler(LoginError)
    def login_error(error: LoginError) -> ResponseReturnValue:
        if isinstance(error, ProviderUnavailableError):
            return jsonify(error="identity_provider_unavailable", message="The identity provider is not reachable"), 502
        _log.warning("request failed", extra={"event": "request.failed", "error": type(error).__name__})
        return jsonify(error="sign_in_required", message="Your session ended. Sign in again."), 401

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> ResponseReturnValue:
        return jsonify(error=error.name.lower().replace(" ", "_"), message=error.name), error.code or 500

    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> ResponseReturnValue:
        _log.exception("unhandled error", extra={"request_id": g.get("request_id"), "path": request.path})
        return jsonify(error="internal_error", message="Something went wrong"), 500
