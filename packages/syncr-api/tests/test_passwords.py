"""The password hash: what it stores, what it accepts, and what it costs.

The encoding is the only part written here rather than by OpenSSL, so it is what these
tests are mostly about: a stored hash has to carry the parameters it was made with, or
raising the cost later would invalidate every existing password.
"""

from __future__ import annotations

import pytest

from syncr_api.accounts.passwords import (
    ALGORITHM,
    SCRYPT_BLOCK_SIZE,
    SCRYPT_COST,
    hash_password,
    verify_password,
)

PASSWORD = "correct-horse-battery-staple"  # pragma: allowlist secret


def test_a_password_verifies_against_its_own_hash() -> None:
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


def test_a_wrong_password_does_not_verify() -> None:
    assert verify_password("not the password", hash_password(PASSWORD)) is False


def test_two_hashes_of_one_password_differ() -> None:
    # Salted per hash, so two accounts with the same password do not have the same row,
    # and a stolen table cannot be attacked once for every user at a time.
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_the_hash_states_the_algorithm_and_the_parameters_it_used() -> None:
    algorithm, cost, block_size, _parallelism, salt, derived = hash_password(PASSWORD).split("$")

    assert algorithm == ALGORITHM
    assert int(cost) == SCRYPT_COST
    assert int(block_size) == SCRYPT_BLOCK_SIZE
    assert salt and derived


def test_a_hash_made_with_weaker_parameters_still_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The reason the parameters are stored: raising the cost must not lock the one
    # account out, so verification reads them from the row rather than from this module's
    # constants. The hash is made at half the cost and verified at the full one.
    weaker_cost = SCRYPT_COST // 2
    with monkeypatch.context() as patched:
        patched.setattr("syncr_api.accounts.passwords.SCRYPT_COST", weaker_cost)
        stored = hash_password(PASSWORD)

    assert stored.split("$")[1] == str(weaker_cost)
    assert verify_password(PASSWORD, stored) is True
    assert verify_password("not the password", stored) is False


def test_no_password_verifies_against_a_missing_user() -> None:
    assert verify_password(PASSWORD, None) is False


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "not-an-encoded-hash",
        "scrypt$32768$8$1$only-five-fields",
        "argon2$32768$8$1$c2FsdA$ZGVyaXZlZA",
        "scrypt$not-a-number$8$1$c2FsdA$ZGVyaXZlZA",
    ],
)
def test_an_unreadable_stored_hash_verifies_as_false_rather_than_raising(stored: str) -> None:
    # A row that cannot be parsed must authenticate nobody, and it must not turn sign-in
    # into a 500 either: either outcome would be worse than a failed sign-in.
    assert verify_password(PASSWORD, stored) is False
