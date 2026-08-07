"""``plan solve`` and ``plan solve --wait``: the whole lifecycle, through the process.

Four endings and three of them are not failures, which is the reason the exit-code table has 9 and
10 at all: an agent that read a supersession as a failure would re-dispatch onto a chain that is
already running, and one that read a timeout as a failure would abandon work that is still going.

**Every ending here is reached through the runner rather than through the wait function.** Ticket
50's exit-code contract could only reach 9 and 10 in its own interpreter, because no command in that
slice dispatched work; ``plan solve --wait`` is what makes both end to end, and the two exemptions
that recorded the gap are deleted with this file.

**The clock is the test's and the loop is the process's.** A supersession and a timeout are reached
in no time at all, because the sleep advances a clock rather than the machine's; nothing about the
poll, the backoff, or the terminal-status mapping is stubbed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_cli.api_client import API_PREFIX
from syncr_cli.auth.discovery import DISCOVERY_PATH
from syncr_cli.exit_codes import ExitCode
from syncr_cli.operations import MAX_POLL_INTERVAL_MS
from tests import payloads
from tests.credentials import NO_KEYCHAIN, seed_refresh_token
from tests.fake_api import Answer, FakeApi
from tests.harness import Clock, drive

if TYPE_CHECKING:
    from pathlib import Path

SOLVE_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}/solve"
OPERATION_PATH: Final = f"{API_PREFIX}/operations/{payloads.OPERATION_ID}"
WEEK_PATH: Final = f"{API_PREFIX}/weeks/{payloads.ISO_WEEK}"
AREAS_PATH: Final = f"{API_PREFIX}/areas"

RUNNING: Final = Answer.json(payloads.operation(status="running"))
ACCEPTED: Final = Answer.json(payloads.operation(), status=202)


def test_a_solve_prints_the_operation_and_exits_zero_immediately(tmp_path: Path) -> None:
    # Without --wait the plan does not exist yet, so the answer is the operation to follow. An agent
    # polls it without guessing an identifier, which is the whole reason it is printed.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)

        ran = drive(("plan", "solve"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN)

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    assert ran.document["operation"]["id"] == payloads.OPERATION_ID
    assert api.requests_to("GET", OPERATION_PATH) == []


def test_immediate_bypasses_the_debounce_on_the_request_itself(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)

        drive(
            ("plan", "solve", "--immediate"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
        )

    assert api.requests_to("POST", SOLVE_PATH)[0].query == {"immediate": ["true"]}


def test_a_wait_that_succeeds_exits_zero_and_prints_the_plan_summary(tmp_path: Path) -> None:
    # The summary is the week's own, so the figures a wait reports and the figures `week show`
    # reports are the same figures rather than a second arithmetic that can disagree.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)
        api.answer_in_turn(
            "GET", OPERATION_PATH, RUNNING, Answer.json(payloads.operation(status="succeeded"))
        )

        ran = drive(
            ("plan", "solve", "--wait"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert ran.code is ExitCode.SUCCESS, ran.stdout
    assert "91 blocks" in ran.stdout
    assert "80.8h scheduled" in ran.stdout
    assert "succeeded" in ran.stdout


def test_a_wait_that_succeeds_on_an_infeasible_week_still_exits_eight(tmp_path: Path) -> None:
    # An infeasible week is the product working correctly, so the solve succeeded and the week
    # cannot hold its commitments. Both are true and the code says the second, because that is the
    # one an agent has to act on.
    with FakeApi() as api:
        _serving(api, tmp_path, week=payloads.week(week_verdict=payloads.verdict()))
        api.answer("POST", SOLVE_PATH, ACCEPTED)
        api.answer("GET", OPERATION_PATH, Answer.json(payloads.operation(status="succeeded")))

        ran = drive(
            ("plan", "solve", "--wait"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN
        )

    assert ran.code is ExitCode.INFEASIBLE, ran.stdout
    assert ran.document["ok"] is True
    assert ran.document["verdict"]["feasible"] is False


def test_a_deliberately_induced_supersession_exits_nine_and_names_its_successor(
    tmp_path: Path,
) -> None:
    # The expected result of editing quickly. It names the operation that displaced it so an agent
    # follows the chain rather than dispatching another solve onto it.
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)
        api.answer_in_turn(
            "GET",
            OPERATION_PATH,
            RUNNING,
            Answer.json(
                payloads.operation(status="superseded", superseded_by=payloads.SUCCESSOR_ID)
            ),
        )

        ran = drive(
            ("plan", "solve", "--wait"), base_url=api.base_url, home=tmp_path, env=NO_KEYCHAIN
        )

    assert ran.code is ExitCode.SUPERSEDED, ran.stdout
    assert ran.document["ok"] is True
    assert ran.document["operation"]["supersededBy"] == payloads.SUCCESSOR_ID


def test_a_wait_on_a_failed_solve_exits_one_with_the_stated_cause(tmp_path: Path) -> None:
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)
        api.answer(
            "GET",
            OPERATION_PATH,
            Answer.json(
                payloads.operation(
                    status="failed",
                    error={"code": "solver_fault", "message": "the solver raised"},
                )
            ),
        )

        ran = drive(
            ("plan", "solve", "--wait"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            stdout_is_tty=True,
        )

    assert ran.code is ExitCode.FAILURE, ran.stdout
    assert "solver_fault: the solver raised" in ran.stdout


def test_a_deliberately_induced_timeout_exits_ten_and_carries_the_operation(
    tmp_path: Path,
) -> None:
    # A timeout says nothing about the work it was waiting on, so it is not a failure of the solve.
    # The operation travels on the wrapper's own member rather than only in the sentence, so an
    # agent resumes the wait without parsing prose for an identifier.
    clock = Clock()
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)
        api.answer("GET", OPERATION_PATH, RUNNING)

        ran = drive(
            ("plan", "solve", "--wait", "--timeout", "60", "--poll-interval", "500"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            clock=clock,
        )

    assert ran.code is ExitCode.TIMED_OUT, ran.stdout
    assert ran.document["ok"] is False
    assert ran.document["operation"]["id"] == payloads.OPERATION_ID
    assert ran.document["problem"]["type"] == "syncr:cli-timed-out"
    assert payloads.OPERATION_ID in ran.document["problem"]["detail"]


def test_the_poll_backs_off_to_its_ceiling_rather_than_hammering_the_api(
    tmp_path: Path,
) -> None:
    # A tight poll on a long solve should not hammer the API. Sixty seconds at the configured 500ms
    # would be 120 requests; capped and doubling it is a dozen.
    clock = Clock()
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)
        api.answer("GET", OPERATION_PATH, RUNNING)

        drive(
            ("plan", "solve", "--wait", "--timeout", "60", "--poll-interval", "500"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            clock=clock,
        )

    polls = api.requests_to("GET", OPERATION_PATH)
    assert clock.slept[0] == 0.5
    assert clock.slept[1] == 1.0
    assert max(clock.slept) <= MAX_POLL_INTERVAL_MS / 1000
    assert len(polls) < 20


def test_a_timed_out_wait_is_resumable_from_the_identifier_it_printed(tmp_path: Path) -> None:
    # The point of printing it. The same week's solve is asked for again, the operation the first
    # wait named is the one the coordinator hands back, and the second wait sees it finish.
    clock = Clock()
    with FakeApi() as api:
        _serving(api, tmp_path)
        api.answer("POST", SOLVE_PATH, ACCEPTED)
        api.answer("GET", OPERATION_PATH, RUNNING)
        timed_out = drive(
            ("plan", "solve", "--wait", "--timeout", "5", "--poll-interval", "500"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            clock=clock,
        )
        api.answer("GET", OPERATION_PATH, Answer.json(payloads.operation(status="succeeded")))
        resumed = drive(
            ("plan", "solve", "--wait"),
            base_url=api.base_url,
            home=tmp_path,
            env=NO_KEYCHAIN,
            clock=Clock(),
        )

    assert timed_out.code is ExitCode.TIMED_OUT
    assert resumed.code is ExitCode.SUCCESS, resumed.stdout
    assert resumed.document["operation"]["id"] == timed_out.document["operation"]["id"]


def _serving(api: FakeApi, home: Path, *, week: dict[str, object] | None = None) -> None:
    """A deployment that discovers, refreshes, and answers the week read a settled wait makes."""
    api.answer("GET", DISCOVERY_PATH, Answer.json(payloads.metadata(api.base_url)))
    api.answer("POST", "/oauth/token", Answer.json(payloads.token_response()))
    api.answer("GET", AREAS_PATH, Answer.json(payloads.areas()))
    api.answer("GET", WEEK_PATH, Answer.json(payloads.week() if week is None else week))
    seed_refresh_token(home, api.base_url)
