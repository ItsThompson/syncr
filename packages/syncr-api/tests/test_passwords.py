"""The password hash: what it stores, what it accepts, and what it costs.

The encoding is the only part written here rather than by OpenSSL, so it is what these
tests are mostly about: a stored hash has to carry the parameters it was made with, or
raising the cost later would invalidate every existing password.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from syncr_api.accounts.passwords import (
    ALGORITHM,
    SCRYPT_BLOCK_SIZE,
    SCRYPT_COST,
    hash_password,
    hash_password_in_thread,
    verify_password,
    verify_password_in_thread,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

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


# --------------------------------------------------------------------------------
# Off the event loop. The derivation holds a CPU for ~120 ms, so an async caller that
# ran it inline would stall every other in-flight request on the same worker for that
# long: an unauthenticated endpoint would then be an availability problem for the whole
# API rather than a slow one for sign-in.
# --------------------------------------------------------------------------------

HEARTBEAT_INTERVAL_SECONDS = 0.005


async def count_heartbeats_during(work: Awaitable[object]) -> int:
    """How many times the event loop got control while ``work`` ran."""
    ticks = 0
    task = asyncio.ensure_future(work)
    while not task.done():
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        ticks += 1
    await task
    return ticks


async def test_the_async_hash_produces_a_hash_its_own_verifier_accepts() -> None:
    stored = await hash_password_in_thread(PASSWORD)

    assert await verify_password_in_thread(PASSWORD, stored) is True
    assert await verify_password_in_thread("not the password", stored) is False
    # The same encoding, so the synchronous bootstrap path and the request path agree.
    assert verify_password(PASSWORD, stored) is True


async def test_the_event_loop_keeps_running_while_a_password_is_verified() -> None:
    stored = hash_password(PASSWORD)

    off_the_loop = await count_heartbeats_during(verify_password_in_thread(PASSWORD, stored))
    # The control: the same derivation called inline, which is what this must not be.
    # Compared rather than given a fixed floor, so the assertion holds on a fast CPU and
    # on a slow one.
    on_the_loop = await count_heartbeats_during(_verified_inline(PASSWORD, stored))

    assert off_the_loop > on_the_loop, (
        f"{off_the_loop} heartbeats off the loop against {on_the_loop} inline: the "
        "derivation is blocking the loop"
    )
    assert off_the_loop >= 2
    assert on_the_loop <= 1


async def test_the_absent_user_path_also_stays_off_the_loop() -> None:
    # The costlier of the two, since it derives and then discards, and the one an
    # attacker reaches without knowing any email.
    ticks = await count_heartbeats_during(verify_password_in_thread(PASSWORD, None))

    assert ticks >= 2


async def _verified_inline(password: str, stored: str) -> bool:
    """The blocking call an async caller must not make. Here only as a control."""
    return verify_password(password, stored)
