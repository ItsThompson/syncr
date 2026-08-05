"""Waiting on an operation: the three terminal endings, the timeout, and the backoff.

The clock and the sleep are injected, so a supersession and a timeout are driven in milliseconds
rather than waited for. The API is a real server, because what the loop polls is a route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from syncr_cli.api_client import ApiClient
from syncr_cli.errors import WaitTimedOut
from syncr_cli.exit_codes import ExitCode
from syncr_cli.operations import BACKOFF_FACTOR, MAX_POLL_INTERVAL_MS, wait_for_operation
from syncr_cli.wire.operation import Operation, OperationStatus
from tests import payloads
from tests.fake_api import Answer, FakeApi

if TYPE_CHECKING:
    from collections.abc import Iterator

OPERATION_PATH = f"/api/v1/operations/{payloads.OPERATION_ID}"


class Clock:
    """A clock a test moves, and the sleeps it was asked for."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class _NoCredential:
    """A session that presents nothing, because the operation route is faked, not authorized."""

    def headers(self) -> dict[str, str]:
        return {}


def client_for(api: FakeApi, transport_client: httpx.Client) -> ApiClient:
    from syncr_cli.http import Transport

    return ApiClient(
        transport=Transport(transport_client),
        api_url=api.base_url,
        session=_NoCredential(),
    )


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=5.0) as client:
        yield client


def test_a_succeeded_operation_ends_the_wait_and_exits_zero(http: httpx.Client) -> None:
    clock = Clock()
    with FakeApi() as api:
        api.answer_in_turn(
            "GET",
            OPERATION_PATH,
            Answer.json(payloads.operation(status="running")),
            Answer.json(payloads.operation(status="succeeded")),
        )

        finished = _wait(api, http, clock)

    assert finished.status is OperationStatus.SUCCEEDED
    assert finished.exit_code is ExitCode.SUCCESS
    assert len(clock.slept) == 1


def test_a_superseded_operation_exits_nine_and_names_its_successor(http: httpx.Client) -> None:
    # A superseded solve is the expected result of editing quickly, so it names the operation that
    # displaced it: an agent follows the chain instead of dispatching another.
    clock = Clock()
    with FakeApi() as api:
        api.answer(
            "GET",
            OPERATION_PATH,
            Answer.json(
                payloads.operation(
                    status="superseded",
                    superseded_by=payloads.SUCCESSOR_ID,
                    statement="A later edit displaced this solve. A follow-up is running.",
                )
            ),
        )

        finished = _wait(api, http, clock)

    assert finished.exit_code is ExitCode.SUPERSEDED
    assert finished.superseded_by == payloads.SUCCESSOR_ID
    assert payloads.SUCCESSOR_ID in finished.summary


def test_a_failed_operation_exits_one_with_the_stated_cause(http: httpx.Client) -> None:
    clock = Clock()
    with FakeApi() as api:
        api.answer(
            "GET",
            OPERATION_PATH,
            Answer.json(
                payloads.operation(
                    status="failed", error={"code": "solver_fault", "message": "the solver raised"}
                )
            ),
        )

        finished = _wait(api, http, clock)

    assert finished.exit_code is ExitCode.FAILURE
    assert "solver_fault: the solver raised" in finished.summary


def test_a_wait_that_runs_out_names_the_operation_so_it_can_be_resumed(
    http: httpx.Client,
) -> None:
    clock = Clock()
    with FakeApi() as api:
        api.answer("GET", OPERATION_PATH, Answer.json(payloads.operation(status="running")))

        with pytest.raises(WaitTimedOut) as timed_out:
            _wait(api, http, clock, timeout_s=1)

    assert timed_out.value.operation_id == payloads.OPERATION_ID
    assert timed_out.value.exit_code is ExitCode.TIMED_OUT
    assert payloads.OPERATION_ID in timed_out.value.detail
    assert "not cancelled" in timed_out.value.detail


def test_the_poll_backs_off_from_the_configured_interval_and_is_capped(
    http: httpx.Client,
) -> None:
    # A tight poll on a long solve should not hammer the API. The first poll is at the configured
    # interval, so a fast solve still answers fast.
    clock = Clock()
    with FakeApi() as api:
        api.answer("GET", OPERATION_PATH, Answer.json(payloads.operation(status="running")))

        with pytest.raises(WaitTimedOut):
            _wait(api, http, clock, poll_interval_ms=500, timeout_s=60)

    assert clock.slept[0] == pytest.approx(0.5)
    assert clock.slept[1] == pytest.approx(0.5 * BACKOFF_FACTOR)
    assert max(clock.slept) <= MAX_POLL_INTERVAL_MS / 1000
    # Capped rather than doubling forever: a minute of waiting is a dozen polls, not a hundred.
    assert len(clock.slept) < 20


def test_a_status_this_build_cannot_recognize_is_refused_rather_than_polled(
    http: httpx.Client,
) -> None:
    # Treating an unknown status as "not terminal yet" would turn a contract change into a wait that
    # ends only at the timeout, which reports the wrong thing about the work.
    clock = Clock()
    with FakeApi() as api:
        api.answer("GET", OPERATION_PATH, Answer.json(payloads.operation(status="abandoned")))

        with pytest.raises(Exception, match="operation is in one of") as refused:
            _wait(api, http, clock)

    assert "abandoned" in str(refused.value)


def test_a_non_terminal_operation_reads_as_success_when_nothing_waited() -> None:
    # A command that dispatched work and did not wait has done what it was asked, and the operation
    # id is in its output.
    running = Operation.read(payloads.operation(status="pending"), "operation")

    assert running.is_terminal is False
    assert running.exit_code is ExitCode.SUCCESS


def test_a_retrying_operation_says_which_attempt_it_is_on() -> None:
    # A count that changes is how progress is reported in this product. There is no spinner.
    retrying = Operation.read(payloads.operation(status="running", attempt=3), "operation")

    assert "attempt 3" in retrying.summary


def _wait(
    api: FakeApi,
    http: httpx.Client,
    clock: Clock,
    *,
    poll_interval_ms: int = 10,
    timeout_s: int = 60,
) -> Operation:
    return wait_for_operation(
        client=client_for(api, http),
        operation_id=payloads.OPERATION_ID,
        poll_interval_ms=poll_interval_ms,
        timeout_s=timeout_s,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
