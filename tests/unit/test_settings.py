import pytest

from oidc_login.infrastructure.settings import ConfigError, Settings

BASE = {
    "OIDC_ISSUER": "http://localhost:8080/realms/demo/",
    "OIDC_CLIENT_ID": "notes-app",
    "OIDC_CLIENT_SECRET": "super-secret-value",
    "OIDC_REDIRECT_URI": "http://localhost:3000/callback",
    "APP_ENV": "development",
}


def test_defaults_and_normalization():
    settings = Settings.from_environment(BASE)
    assert settings.issuer == "http://localhost:8080/realms/demo"  # no trailing slash
    assert settings.discovery_base == settings.issuer
    assert settings.port == 3000
    assert settings.cookie_secure is True
    assert settings.allowed_extra_scopes == frozenset({"reports:read"})
    assert (settings.session_idle_seconds, settings.session_absolute_seconds) == (900, 28800)


def test_the_client_secret_is_never_printed():
    assert "super-secret-value" not in repr(Settings.from_environment(BASE))


@pytest.mark.parametrize("name", ["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"])
def test_required_settings_are_required(name):
    env = {key: value for key, value in BASE.items() if key != name}
    with pytest.raises(ConfigError, match=name):
        Settings.from_environment(env)


def test_the_environment_name_must_be_known():
    with pytest.raises(ConfigError, match="APP_ENV"):
        Settings.from_environment({**BASE, "APP_ENV": "staging"})


@pytest.mark.parametrize(
    "uri",
    [
        "/callback",
        "ftp://localhost/callback",
        "http://localhost:3000/callback?x=1",
        "http://localhost:3000/callback#f",
        "http://",
    ],
)
def test_a_redirect_uri_must_be_an_absolute_http_url_without_query_or_fragment(uri):
    with pytest.raises(ConfigError, match="OIDC_REDIRECT_URI"):
        Settings.from_environment({**BASE, "OIDC_REDIRECT_URI": uri})


def test_plain_http_is_for_localhost_only():
    with pytest.raises(ConfigError, match="only accepted for localhost"):
        Settings.from_environment({**BASE, "OIDC_REDIRECT_URI": "http://app.example.test/callback"})
    assert Settings.from_environment(
        {**BASE, "OIDC_REDIRECT_URI": "https://app.example.test/callback"}
    ).redirect_uri.startswith("https")


def test_production_requires_https_everywhere_and_secure_cookies():
    production = {**BASE, "APP_ENV": "production"}
    with pytest.raises(ConfigError, match="https in production"):
        Settings.from_environment(production)
    https = {
        **production,
        "OIDC_REDIRECT_URI": "https://app.example.test/callback",
        "OIDC_ISSUER": "https://id.example.test/realms/demo",
    }
    assert Settings.from_environment(https).app_env == "production"
    with pytest.raises(ConfigError, match="COOKIE_SECURE"):
        Settings.from_environment({**https, "COOKIE_SECURE": "false"})
    with pytest.raises(ConfigError, match="OIDC_ISSUER must use https"):
        Settings.from_environment({**https, "OIDC_ISSUER": "http://id.example.test/realms/demo"})


def test_the_issuer_must_be_a_url_and_integers_are_checked():
    with pytest.raises(ConfigError, match="OIDC_ISSUER"):
        Settings.from_environment({**BASE, "OIDC_ISSUER": "localhost"})
    with pytest.raises(ConfigError, match="APP_PORT"):
        Settings.from_environment({**BASE, "APP_PORT": "abc"})
    with pytest.raises(ConfigError, match="APP_PORT"):
        Settings.from_environment({**BASE, "APP_PORT": "0"})
    with pytest.raises(ConfigError, match="SESSION_IDLE_SECONDS"):
        Settings.from_environment({**BASE, "SESSION_IDLE_SECONDS": "99999"})


def test_an_empty_extra_scope_list_allows_none():
    assert Settings.from_environment({**BASE, "OIDC_ALLOWED_EXTRA_SCOPES": ""}).allowed_extra_scopes == frozenset()
