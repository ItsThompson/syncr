"""Idempotency-key derivation: stable for one invocation, different for another.

The property the api depends on is stability. An agent retrying a mutation must present the same
key, so the derivation reads the command and its arguments and nothing else: no clock, no random
source, no process identity, and no dependence on the order a parser filled the arguments in.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from syncr_cli.errors import UsageError
from syncr_cli.idempotency import DERIVED_KEY_PREFIX, KEY_MAX_LENGTH, derive_key, supplied_key

COMMAND = ("task", "add")
ARGUMENTS: dict[str, object] = {"title": "Write the spec", "estimateMinutes": 90}


def test_the_same_command_and_arguments_derive_the_same_key() -> None:
    assert derive_key(COMMAND, ARGUMENTS) == derive_key(COMMAND, ARGUMENTS)


def test_the_order_the_arguments_were_stated_in_does_not_change_the_key() -> None:
    reordered = {name: ARGUMENTS[name] for name in reversed(list(ARGUMENTS))}

    assert derive_key(COMMAND, reordered) == derive_key(COMMAND, ARGUMENTS)


def test_an_argument_the_user_did_not_state_does_not_change_the_key() -> None:
    # An absent argument and one stated as null are the same request, so carrying the distinction
    # would give one request two keys and defeat the retry the header exists for.
    assert derive_key(COMMAND, {**ARGUMENTS, "projectId": None}) == derive_key(COMMAND, ARGUMENTS)


@pytest.mark.parametrize(
    "different",
    [
        {"title": "Write the spec", "estimateMinutes": 91},
        {"title": "Write the other spec", "estimateMinutes": 90},
        {"title": "Write the spec"},
    ],
)
def test_a_different_request_derives_a_different_key(different: dict[str, object]) -> None:
    assert derive_key(COMMAND, different) != derive_key(COMMAND, ARGUMENTS)


def test_a_different_command_with_one_argument_set_derives_a_different_key() -> None:
    assert derive_key(("task", "done"), ARGUMENTS) != derive_key(COMMAND, ARGUMENTS)


def test_a_value_that_is_not_json_still_derives_a_key() -> None:
    # Arguments arrive as identifiers and dates as well as strings, and a derivation that faulted
    # on one would refuse the mutation rather than key it.
    identifier = UUID("11111111-1111-4111-8111-111111111111")

    assert derive_key(("block", "move"), {"blockId": identifier}) == derive_key(
        ("block", "move"), {"blockId": identifier}
    )


def test_a_derived_key_is_recognizable_and_inside_the_bound_the_api_enforces() -> None:
    key = derive_key(COMMAND, ARGUMENTS)

    assert key.startswith(DERIVED_KEY_PREFIX)
    assert len(key) <= KEY_MAX_LENGTH


def test_a_supplied_key_is_taken_as_stated() -> None:
    assert supplied_key("  batch-7  ") == "batch-7"


def test_a_supplied_key_that_is_empty_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="carries no value"):
        supplied_key("   ")


def test_a_supplied_key_past_the_bound_is_refused_here_rather_than_by_the_api() -> None:
    with pytest.raises(UsageError, match=str(KEY_MAX_LENGTH)):
        supplied_key("k" * (KEY_MAX_LENGTH + 1))
