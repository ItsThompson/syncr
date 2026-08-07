"""Running a mutation twice with the same key applies it once.

The CLI's half of the obligation is a key that is the same for the same invocation, so a retry after
a timeout is a retry rather than a second act. The api's half is a guard that stores the response
per key and replays it. Both halves are here: the server declares the route idempotent, which is
what the guard does, and the assertion counts the acts rather than the requests.

**Counting requests would prove nothing.** A retry sends a second request by definition. What
matters is how many distinct keys the route saw, because a key is what the guard deduplicates on.

**The derivation is asserted in both directions.** A key that never changed would pass the first
half of every case here and make two genuinely different mutations one, so each case also runs with
one argument changed and asserts the route saw two acts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pytest

from syncr_cli.api_client import API_PREFIX
from syncr_cli.auth.discovery import DISCOVERY_PATH
from tests import payloads
from tests.credentials import NO_KEYCHAIN, seed_refresh_token
from tests.fake_api import Answer, FakeApi
from tests.harness import drive

if TYPE_CHECKING:
    from pathlib import Path

TASKS_PATH: Final = f"{API_PREFIX}/tasks"
COMPLETE_PATH: Final = f"{API_PREFIX}/tasks/{payloads.TASK_ID}/complete"
OUTCOME_PATH: Final = f"{API_PREFIX}/blocks/{payloads.BLOCK_ID}/outcome"
CONFIRM_PATH: Final = f"{API_PREFIX}/days/{payloads.TUESDAY.isoformat()}/confirm"
PINS_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/pins"
APPROVE_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/approve"

MOVED_TO: Final = "2026-02-10T07:00:00+00:00"
ELSEWHERE: Final = "2026-02-10T08:00:00+00:00"


@dataclass(frozen=True, slots=True)
class Mutation:
    """One mutation, its route, and the same invocation with one argument changed."""

    argv: tuple[str, ...]
    method: str
    path: str
    answer: Answer
    different: tuple[str, ...]


MUTATIONS: Final = (
    Mutation(
        argv=("task", "add", "Leetcode", "--area", str(payloads.CAREER_ID)),
        method="POST",
        path=TASKS_PATH,
        answer=Answer.json(payloads.task(), status=201),
        different=("task", "add", "Something else", "--area", str(payloads.CAREER_ID)),
    ),
    Mutation(
        argv=("task", "done", payloads.TASK_ID),
        method="POST",
        path=COMPLETE_PATH,
        answer=Answer.json(payloads.task(status="completed")),
        # A different task is a different act, and the route is per-task, so the changed argument is
        # the idempotency key itself: an agent that means two of one act says so.
        different=("task", "done", payloads.TASK_ID, "--idempotency-key", "deliberately-second"),
    ),
    Mutation(
        argv=("block", "done", payloads.BLOCK_ID),
        method="PUT",
        path=OUTCOME_PATH,
        answer=Answer.json(payloads.outcome()),
        different=("block", "skip", payloads.BLOCK_ID),
    ),
    Mutation(
        argv=("block", "partial", payloads.BLOCK_ID, "--minutes", "45"),
        method="PUT",
        path=OUTCOME_PATH,
        answer=Answer.json(payloads.outcome(state="partial", actual_minutes=45)),
        different=("block", "partial", payloads.BLOCK_ID, "--minutes", "50"),
    ),
    Mutation(
        argv=("block", "move", payloads.BLOCK_ID, "--to", MOVED_TO),
        method="POST",
        path=PINS_PATH,
        answer=Answer.json(payloads.pinned(), status=201),
        different=("block", "move", payloads.BLOCK_ID, "--to", ELSEWHERE),
    ),
    Mutation(
        argv=("day", "confirm", payloads.TUESDAY.isoformat()),
        method="POST",
        path=CONFIRM_PATH,
        answer=Answer.json(payloads.day()),
        different=(
            "day",
            "confirm",
            payloads.TUESDAY.isoformat(),
            "--idempotency-key",
            "deliberately-second",
        ),
    ),
    Mutation(
        argv=(
            "plan",
            "approve",
        ),
        method="POST",
        path=APPROVE_PATH,
        answer=Answer.json(payloads.approved(), status=201),
        different=("plan", "approve", "--idempotency-key", "deliberately-second"),
    ),
)


def _identify(mutation: Mutation) -> str:
    return " ".join(mutation.argv[:2])


@pytest.mark.parametrize("mutation", MUTATIONS, ids=_identify)
def test_the_same_invocation_twice_is_one_act(mutation: Mutation, tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer_once_per_key(mutation.method, mutation.path, mutation.answer)

        first = drive(mutation.argv, base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)
        second = drive(mutation.argv, base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

        assert first.code == 0, first.stdout
        assert second.code == 0, second.stdout
        assert len(api.requests_to(mutation.method, mutation.path)) == 2
        assert api.applications_of(mutation.method, mutation.path) == 1


@pytest.mark.parametrize("mutation", MUTATIONS, ids=_identify)
def test_a_genuinely_different_invocation_is_a_second_act(
    mutation: Mutation, tmp_path: Path
) -> None:
    # The other direction. A derivation that ignored its arguments would make every case above pass
    # and would silently collapse two real mutations into one.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer_once_per_key(mutation.method, mutation.path, mutation.answer)

        drive(mutation.argv, base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)
        drive(mutation.different, base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

        assert api.applications_of(mutation.method, mutation.path) == 2


def test_the_solve_route_carries_no_key_and_is_therefore_not_replayed(tmp_path: Path) -> None:
    """The one deliberate exception, asserted rather than assumed.

    A solve is idempotent per week by the coordinator's single-flight invariant, so a derived key
    would be the same key tomorrow and the guard would replay a completed operation rather than
    dispatching a solve of a week that has moved on.
    """
    solve = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/solve"
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", solve, Answer.json(payloads.operation(), status=202))

        drive(("plan", "solve"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)
        drive(("plan", "solve"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

        sent = api.requests_to("POST", solve)
        assert len(sent) == 2
        assert all("idempotency-key" not in one.headers for one in sent)


def _serving(api: FakeApi, home: Path) -> None:
    api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
    api.answer("POST", "/oauth/token", Answer.json(payloads.token_response()))
    seed_refresh_token(home, api.base_url)
