"""The composition root: the one place that knows which adapter implements which port."""

from __future__ import annotations

from dataclasses import dataclass

from oidc_login.application.login_flow import LoginConfig, LoginService
from oidc_login.infrastructure.clock import SecretsTokenGenerator, SystemClock
from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier
from oidc_login.infrastructure.memory_stores import InMemoryPendingLoginStore, InMemorySessionStore
from oidc_login.infrastructure.oidc_provider import OidcProvider
from oidc_login.infrastructure.settings import Settings


@dataclass(frozen=True, slots=True)
class Container:
    """The wired application."""

    settings: Settings
    provider: OidcProvider
    flow: LoginService
    sessions: InMemorySessionStore


def build_container(settings: Settings) -> Container:
    """Wire the provider adapter, the verifier, the in-memory stores and the flow."""
    clock = SystemClock()
    provider = OidcProvider(
        issuer=settings.issuer,
        discovery_base=settings.discovery_base,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.redirect_uri,
        timeout_seconds=settings.http_timeout_seconds,
    )
    sessions = InMemorySessionStore()
    flow = LoginService(
        provider=provider,
        verifier=JwksTokenVerifier(provider.jwks),
        pending=InMemoryPendingLoginStore(clock, settings.pending_ttl_seconds),
        sessions=sessions,
        clock=clock,
        tokens=SecretsTokenGenerator(),
        config=LoginConfig(
            issuer=settings.issuer,
            client_id=settings.client_id,
            allowed_extra_scopes=settings.allowed_extra_scopes,
            pending_ttl_seconds=settings.pending_ttl_seconds,
            session_idle_seconds=settings.session_idle_seconds,
            session_absolute_seconds=settings.session_absolute_seconds,
            refresh_margin_seconds=settings.refresh_margin_seconds,
        ),
    )
    return Container(settings=settings, provider=provider, flow=flow, sessions=sessions)
