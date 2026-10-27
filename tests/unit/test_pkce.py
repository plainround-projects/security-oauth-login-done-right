import pytest

from oidc_login.domain.pkce import challenge_for, is_valid_verifier


def test_the_challenge_matches_the_rfc_7636_appendix_b_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_challenge_has_no_padding_and_is_url_safe():
    challenge = challenge_for("a" * 64)
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge
    assert len(challenge) == 43


@pytest.mark.parametrize("verifier", ["a" * 43, "a" * 128, "A-._~" + "b" * 40])
def test_verifiers_of_43_to_128_unreserved_characters_are_valid(verifier):
    assert is_valid_verifier(verifier)


@pytest.mark.parametrize("verifier", ["", "short", "a" * 42, "a" * 129, "has space" + "a" * 40, "plus+" + "a" * 40])
def test_other_verifiers_are_refused(verifier):
    assert not is_valid_verifier(verifier)
    with pytest.raises(ValueError, match="43 to 128"):
        challenge_for(verifier)
