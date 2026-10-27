import base64
import hashlib
import hmac
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from oidc_login.domain.errors import SignatureInvalidError, UnsupportedAlgorithmError
from oidc_login.infrastructure.jwks_verifier import JwksTokenVerifier
from tests.fakes import FakeClock, Signer, id_token_claims


@pytest.fixture
def signer():
    return Signer("key-1")


def claims():
    return id_token_claims(FakeClock(), nonce="n")


def verifier_for(signer, **kwargs):
    return JwksTokenVerifier(signer.jwks, **kwargs)


def test_a_token_signed_by_the_published_key_verifies_and_returns_its_claims(signer):
    assert verifier_for(signer).verify(signer.mint(claims()))["sub"] == "user-1"


def test_a_token_signed_by_a_different_key_with_the_same_kid_is_rejected_for_its_signature(signer):
    forger = Signer("key-1")
    with pytest.raises(SignatureInvalidError, match="signature verification failed"):
        verifier_for(signer).verify(forger.mint(claims()))


def test_a_token_with_one_changed_byte_in_its_claims_is_rejected(signer):
    header, payload, signature = signer.mint(claims()).split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["sub"] = "admin"
    forged_payload = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    with pytest.raises(SignatureInvalidError):
        verifier_for(signer).verify(f"{header}.{forged_payload}.{signature}")


def test_the_none_algorithm_is_refused_before_any_key_is_looked_up(signer):
    unsigned = jwt.encode(claims(), key="", algorithm="none", headers={"kid": "key-1"})
    with pytest.raises(UnsupportedAlgorithmError, match="'none'"):
        verifier_for(signer).verify(unsigned)


def test_algorithm_confusion_with_the_public_key_as_an_hmac_secret_is_refused(signer):
    # The classic attack: sign with HS256 using the (public) RSA key as the secret. PyJWT itself refuses to build such a
    # token, so it is assembled by hand.
    public_pem = signer.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    signing_input = f"{part({'alg': 'HS256', 'typ': 'JWT', 'kid': 'key-1'})}.{part(claims())}"
    mac = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    confused = f"{signing_input}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"
    with pytest.raises(UnsupportedAlgorithmError, match="HS256"):
        verifier_for(signer).verify(confused)


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "....", "eyJhbGciOiJSUzI1NiJ9"])
def test_malformed_tokens_are_rejected_without_an_unexpected_error(signer, garbage):
    with pytest.raises(SignatureInvalidError):
        verifier_for(signer).verify(garbage)


def test_a_token_without_a_kid_is_rejected(signer):
    token = jwt.encode(claims(), signer.private_key, algorithm="RS256")
    with pytest.raises(SignatureInvalidError, match="kid"):
        verifier_for(signer).verify(token)


def test_an_unknown_kid_refetches_the_keys_once_and_picks_up_a_rotated_key():
    old, new = Signer("old"), Signer("new")
    published = {"current": old}
    verifier = JwksTokenVerifier(lambda: published["current"].jwks(), min_refresh_seconds=0)
    assert verifier.verify(old.mint(claims()))["sub"] == "user-1"
    published["current"] = new  # the provider rotates
    assert verifier.verify(new.mint(claims()))["sub"] == "user-1"


def test_forged_tokens_cannot_make_the_app_refetch_keys_more_than_once_per_interval(signer):
    fetches = []
    clock = {"now": 0.0}

    def fetch():
        fetches.append(clock["now"])
        return signer.jwks()

    verifier = JwksTokenVerifier(fetch, min_refresh_seconds=30, monotonic=lambda: clock["now"])
    stranger = Signer("unknown-kid")
    for second in (0, 1, 2, 3):  # a burst of forged tokens inside one interval
        clock["now"] = float(second)
        with pytest.raises(SignatureInvalidError, match="signing key not found"):
            verifier.verify(stranger.mint(claims()))
    assert fetches == [0.0]
    clock["now"] = 31.0  # the interval has passed: one more look is allowed
    with pytest.raises(SignatureInvalidError, match="signing key not found"):
        verifier.verify(stranger.mint(claims()))
    assert fetches == [0.0, 31.0]


def test_keys_not_meant_for_signing_and_malformed_keys_are_ignored(signer):
    document = signer.jwks()
    document["keys"].insert(0, {"kty": "RSA", "kid": "enc-key", "use": "enc", "n": "AQAB", "e": "AQAB"})
    document["keys"].insert(0, {"kty": "RSA", "kid": "broken", "use": "sig", "alg": "RS256"})
    document["keys"].insert(
        0, {"kty": "RSA", "kid": "other-alg", "use": "sig", "alg": "PS256", "n": "AQAB", "e": "AQAB"}
    )
    document["keys"].insert(0, "not an object")
    verifier = JwksTokenVerifier(lambda: document)
    assert verifier.verify(signer.mint(claims()))["sub"] == "user-1"
    with pytest.raises(SignatureInvalidError, match="signing key not found"):
        verifier.verify(Signer("enc-key").mint(claims()))


def test_expired_claims_are_not_the_verifiers_business(signer):
    expired = id_token_claims(FakeClock(), nonce="n", exp=1)
    assert (
        verifier_for(signer).verify(signer.mint(expired))["exp"] == 1
    )  # the domain judges expiry, after the signature
