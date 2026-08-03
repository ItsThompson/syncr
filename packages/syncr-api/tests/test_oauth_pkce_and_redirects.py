"""PKCE, the redirect policy, and the opaque secrets: the pure rules, and their controls.

Each rule here is one a public client's whole security rests on, and each is asserted in both
directions. A test that only proves the good case passes on an implementation that accepts
everything.
"""

from __future__ import annotations

import pytest

from syncr_api.oauth.pkce import (
    CHALLENGE_LENGTH,
    VERIFIER_MAX_LENGTH,
    VERIFIER_MIN_LENGTH,
    derive_s256_challenge,
    is_well_formed_challenge,
    is_well_formed_verifier,
    verifies,
)
from syncr_api.oauth.redirects import is_loopback, is_registered_redirect
from syncr_api.oauth.secrets import (
    AUTHORIZATION_CODE_PREFIX,
    DIGEST_LENGTH,
    REFRESH_TOKEN_PREFIX,
    digest_of,
    mint_authorization_code,
    mint_refresh_token,
)

# RFC 7636 appendix B's worked example, so the transform is checked against the
# specification's own numbers rather than against itself. Both values are published in the
# RFC, so neither is a secret.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"  # pragma: allowlist secret

VERIFIER = "a" * VERIFIER_MIN_LENGTH
CLI_REDIRECTS = ("http://127.0.0.1/callback", "http://[::1]/callback")


# --- PKCE ----------------------------------------------------------------------------


def test_the_challenge_matches_the_specifications_own_worked_example() -> None:
    assert derive_s256_challenge(RFC_VERIFIER) == RFC_CHALLENGE


def test_a_verifier_verifies_against_its_own_challenge() -> None:
    assert verifies(RFC_VERIFIER, RFC_CHALLENGE)


def test_another_verifier_does_not() -> None:
    # The control. Without it, a `verifies` that returned True unconditionally would pass
    # every other assertion in this file.
    assert not verifies("b" * VERIFIER_MIN_LENGTH, RFC_CHALLENGE)


def test_a_plain_challenge_never_verifies_even_against_its_own_verifier() -> None:
    # `plain` means the challenge IS the verifier. This is the property that makes refusing
    # the method at the edge more than a formality: even if one arrived, it cannot verify,
    # because the stored challenge would have to be a SHA-256 digest to be well formed.
    plain_verifier = RFC_VERIFIER

    assert not verifies(plain_verifier, plain_verifier)


@pytest.mark.parametrize(
    ("verifier", "expected"),
    [
        ("a" * VERIFIER_MIN_LENGTH, True),
        ("a" * VERIFIER_MAX_LENGTH, True),
        ("a" * (VERIFIER_MIN_LENGTH - 1), False),
        ("a" * (VERIFIER_MAX_LENGTH + 1), False),
        ("-._~" + "a" * VERIFIER_MIN_LENGTH, True),
        ("!" + "a" * VERIFIER_MIN_LENGTH, False),
        ("", False),
    ],
    ids=["floor", "ceiling", "under", "over", "unreserved", "reserved character", "empty"],
)
def test_the_verifier_shape_rules_are_the_rfcs(verifier: str, expected: bool) -> None:
    assert is_well_formed_verifier(verifier) is expected


@pytest.mark.parametrize(
    ("challenge", "expected"),
    [
        (RFC_CHALLENGE, True),
        ("a" * CHALLENGE_LENGTH, True),
        ("a" * (CHALLENGE_LENGTH - 1), False),
        (f"{'a' * (CHALLENGE_LENGTH - 1)}=", False),
        ("", False),
    ],
    ids=["real", "right length", "short", "padded", "empty"],
)
def test_only_a_digest_shaped_value_is_a_challenge(challenge: str, expected: bool) -> None:
    assert is_well_formed_challenge(challenge) is expected


def test_a_malformed_verifier_cannot_verify_however_the_challenge_was_derived() -> None:
    short = "a" * (VERIFIER_MIN_LENGTH - 1)

    assert not verifies(short, derive_s256_challenge(short))


# --- Redirects -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("http://127.0.0.1:54321/callback", True),
        ("http://[::1]:54321/callback", True),
        ("http://localhost:54321/callback", True),
        ("https://127.0.0.1/callback", False),
        ("http://127.0.0.2/callback", False),
        ("http://evil.example/callback", False),
        ("http://127.0.0.1.evil.example/callback", False),
    ],
    ids=["ipv4", "ipv6", "name", "https", "near miss", "remote", "suffix attack"],
)
def test_only_this_machine_is_loopback(uri: str, expected: bool) -> None:
    assert is_loopback(uri) is expected


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("http://127.0.0.1:54321/callback", True),
        ("http://127.0.0.1:1/callback", True),
        ("http://[::1]:54321/callback", True),
        ("http://127.0.0.1:54321/somewhere-else", False),
        ("https://127.0.0.1/callback", False),
        ("https://syncr.example/callback", False),
        ("http://attacker.example/callback", False),
        ("", False),
    ],
    ids=[
        "any port",
        "another port",
        "ipv6 any port",
        "another path",
        "https loopback",
        "remote https",
        "remote http",
        "empty",
    ],
)
def test_the_cli_client_may_only_receive_a_code_on_this_machine(
    requested: str, expected: bool
) -> None:
    assert is_registered_redirect(requested, CLI_REDIRECTS, loopback_only=True) is expected


def test_a_loopback_only_client_is_refused_a_registered_remote_uri() -> None:
    # A registration mistake must not widen the restriction: the client's own rule is
    # checked, not only the list.
    registered = (*CLI_REDIRECTS, "https://syncr.example/callback")

    assert not is_registered_redirect(
        "https://syncr.example/callback", registered, loopback_only=True
    )
    assert is_registered_redirect("https://syncr.example/callback", registered, loopback_only=False)


def test_a_non_loopback_client_is_matched_exactly() -> None:
    registered = ("https://syncr.example/callback",)

    assert is_registered_redirect("https://syncr.example/callback", registered, loopback_only=False)
    assert not is_registered_redirect(
        "https://syncr.example/callback?extra=1", registered, loopback_only=False
    )


# --- Secrets -------------------------------------------------------------------------


def test_a_minted_code_is_recognizable_and_unguessable() -> None:
    code = mint_authorization_code()

    assert code.startswith(AUTHORIZATION_CODE_PREFIX)
    # 32 bytes as URL-safe base64 without padding.
    assert len(code) == len(AUTHORIZATION_CODE_PREFIX) + 43
    assert code != mint_authorization_code()


def test_a_minted_refresh_token_is_recognizable_and_unguessable() -> None:
    token = mint_refresh_token()

    assert token.startswith(REFRESH_TOKEN_PREFIX)
    assert len(token) == len(REFRESH_TOKEN_PREFIX) + 43
    assert token != mint_refresh_token()


def test_the_two_secret_kinds_cannot_be_mistaken_for_each_other() -> None:
    assert AUTHORIZATION_CODE_PREFIX != REFRESH_TOKEN_PREFIX


def test_the_stored_digest_carries_nothing_of_the_secret() -> None:
    secret = mint_refresh_token()

    stored = digest_of(secret)

    assert len(stored) == DIGEST_LENGTH
    assert stored == digest_of(secret), "the digest must be stable, or no row can be found"
    assert secret not in stored
    assert digest_of(secret) != digest_of(mint_refresh_token())
