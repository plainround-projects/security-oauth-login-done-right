from datetime import timedelta

import pytest

from oidc_login.domain.claims import Expectations, check_access_token_hash, check_id_token_claims
from oidc_login.domain.errors import (
    AudienceMismatchError,
    AuthorizedPartyMismatchError,
    IssuerMismatchError,
    MissingClaimError,
    NonceMismatchError,
    TokenExpiredError,
    TokenNotYetValidError,
    TokenValidationError,
)
from tests.fakes import CLIENT_ID, ISSUER, START, FakeClock, access_token_hash, id_token_claims

NONCE = "the-nonce-this-login-sent"
EXPECTED = Expectations(issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE, now=START)


def claims(**overrides):
    return id_token_claims(FakeClock(), nonce=NONCE, **overrides)


def test_a_good_token_yields_the_identity():
    identity = check_id_token_claims(claims(), EXPECTED)
    assert (identity.subject, identity.username, identity.email) == ("user-1", "demo-user", "demo-user@example.test")


def test_the_username_falls_back_to_the_subject():
    identity = check_id_token_claims(claims(preferred_username=None, email=None), EXPECTED)
    assert (identity.username, identity.email) == ("user-1", None)


@pytest.mark.parametrize(
    ("overrides", "error", "reason"),
    [
        (
            {"iss": "http://evil.example.test/realms/demo"},
            IssuerMismatchError,
            "issuer claim does not match the provider",
        ),
        ({"iss": ISSUER + "/"}, IssuerMismatchError, "issuer"),
        ({"aud": "some-other-client"}, AudienceMismatchError, "audience claim does not match client id"),
        ({"aud": ["a", "b"]}, AudienceMismatchError, "audience"),
        ({"aud": [CLIENT_ID, "other"], "azp": "other"}, AuthorizedPartyMismatchError, "authorized party"),
        ({"exp": int(START.timestamp()) - 300}, TokenExpiredError, "token has expired"),
        ({"iat": int(START.timestamp()) + 3600}, TokenNotYetValidError, "not valid yet"),
        ({"nonce": "another-logins-nonce"}, NonceMismatchError, "nonce mismatch: possible token substitution"),
        ({"nonce": None}, NonceMismatchError, "nonce"),
        ({"sub": None}, MissingClaimError, "'sub'"),
        ({"sub": ""}, MissingClaimError, "'sub'"),
        ({"exp": None}, MissingClaimError, "'exp'"),
        ({"exp": "tomorrow"}, MissingClaimError, "'exp'"),
        ({"aud": None}, MissingClaimError, "'aud'"),
        ({"aud": 7}, MissingClaimError, "'aud'"),
    ],
)
def test_each_failed_check_raises_its_own_error_with_a_specific_reason(overrides, error, reason):
    body = {key: value for key, value in claims().items() if overrides.get(key, ...) is not None}
    body.update({key: value for key, value in overrides.items() if value is not None})
    with pytest.raises(error, match=reason) as raised:
        check_id_token_claims(body, EXPECTED)
    assert isinstance(raised.value, TokenValidationError)


def test_several_audiences_are_fine_when_the_authorized_party_is_this_client():
    identity = check_id_token_claims(claims(aud=[CLIENT_ID, "account"], azp=CLIENT_ID), EXPECTED)
    assert identity.subject == "user-1"


def test_a_little_clock_skew_is_tolerated_but_not_a_lot():
    skewed = claims(exp=int(START.timestamp()) - 10)
    assert check_id_token_claims(skewed, EXPECTED).subject == "user-1"  # 10 s late, 30 s leeway
    with pytest.raises(TokenExpiredError):
        check_id_token_claims(claims(exp=int(START.timestamp()) - 31), EXPECTED)
    future = claims(iat=int(START.timestamp()) + 29)
    assert check_id_token_claims(future, EXPECTED).subject == "user-1"


def test_expiry_is_judged_at_the_time_given_not_the_wall_clock():
    later = Expectations(
        issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE, now=START + timedelta(days=1), leeway=timedelta(0)
    )
    with pytest.raises(TokenExpiredError):
        check_id_token_claims(claims(), later)


def test_the_access_token_hash_is_checked_when_present_and_optional_when_absent():
    check_access_token_hash({"at_hash": access_token_hash("the-access-token")}, "the-access-token")
    check_access_token_hash({}, "anything")
    with pytest.raises(TokenValidationError, match="access token hash"):
        check_access_token_hash({"at_hash": access_token_hash("one")}, "another")
    with pytest.raises(TokenValidationError, match="access token hash"):
        check_access_token_hash({"at_hash": 5}, "another")
