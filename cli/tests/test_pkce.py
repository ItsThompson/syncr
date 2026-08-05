"""PKCE, against the RFC's own published worked example.

The transform has two implementations in this repository -- one here and one in the api that
verifies it -- and the specification's example is what crosses them. A test that only checked
``derive_challenge(v) == derive_challenge(v)`` would pass on a transform that agreed with itself
and with nothing else.
"""

from __future__ import annotations

from syncr_cli.auth.pkce import (
    CODE_CHALLENGE_METHOD_S256,
    VERIFIER_ENTROPY_BYTES,
    derive_challenge,
    generate_verifier,
)

# RFC 7636 Appendix B. Both values are published in the specification, so neither is a secret;
# the scanner sees two 43-character base64 strings and cannot know that, which is what the pragma
# says. The api's own suite marks the same verifier the same way.
WORKED_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
WORKED_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"  # pragma: allowlist secret

# RFC 7636 section 4.1: the unreserved set, and 43 characters at the floor.
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_VERIFIER_MIN_LENGTH = 43


def test_the_challenge_matches_the_specifications_worked_example() -> None:
    assert derive_challenge(WORKED_VERIFIER) == WORKED_CHALLENGE


def test_a_generated_verifier_satisfies_the_rfcs_length_and_alphabet() -> None:
    verifier = generate_verifier()

    assert len(verifier) >= _VERIFIER_MIN_LENGTH
    assert set(verifier) <= _UNRESERVED


def test_two_verifiers_are_not_the_same_verifier() -> None:
    assert generate_verifier() != generate_verifier()


def test_the_verifier_carries_the_entropy_the_module_claims() -> None:
    # 32 bytes is 43 unpadded base64url characters, which is the RFC's floor. A smaller figure
    # would produce a verifier the Authorization Server refuses on length.
    assert VERIFIER_ENTROPY_BYTES == 32


def test_the_only_method_this_client_speaks_is_s256() -> None:
    # `plain` is a challenge that IS the verifier, so it proves nothing against anyone who saw the
    # authorize request. RFC 7636 reads an absent method as `plain`, which is why the constant
    # exists rather than the parameter being omitted.
    assert CODE_CHALLENGE_METHOD_S256 == "S256"
