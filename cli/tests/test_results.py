"""The wrapper: which of three readings decides the exit code, and in what order.

The order is the assertion. A problem is why the command failed, so it wins. An operation **this
invocation dispatched** is the outcome of what it asked for, so it outranks the verdict of a plan
that work did not replace. An infeasible verdict is last, and it is not a failure.

An operation a command merely read is reported and does not vote: a successful read must not exit by
the status of work nobody here asked for.
"""

from __future__ import annotations

from syncr_cli.exit_codes import ExitCode
from syncr_cli.problems import cli_problem
from syncr_cli.results import CliResult
from syncr_cli.wire.operation import Operation
from syncr_cli.wire.verdict import Verdict
from tests import payloads


def verdict(**overrides: object) -> Verdict:
    return Verdict.read(payloads.verdict(**overrides), "verdict")  # type: ignore[arg-type]


def operation(**overrides: object) -> Operation:
    return Operation.read(payloads.operation(**overrides), "operation")  # type: ignore[arg-type]


def test_a_bare_success_exits_zero() -> None:
    assert CliResult.succeeded().exit_code is ExitCode.SUCCESS


def test_a_problem_decides_the_code() -> None:
    problem = cli_problem("syncr:cli-usage", "Usage error", "no such flag")

    assert CliResult.failed(problem).exit_code is ExitCode.USAGE


def test_an_infeasible_verdict_exits_eight_on_a_successful_command() -> None:
    result = CliResult.succeeded(verdict=verdict())

    assert result.ok is True
    assert result.exit_code is ExitCode.INFEASIBLE


def test_a_capacity_check_that_found_nothing_exits_zero() -> None:
    # A probe verdict may never claim a week is feasible, so `feasible` stays false and the reading
    # that matters is that it found no gap.
    result = CliResult.succeeded(verdict=verdict(shortfalls=[]))

    assert result.exit_code is ExitCode.SUCCESS


def test_a_solver_verdict_that_failed_to_pack_exits_eight_even_with_no_gap_named() -> None:
    # It attempted a placement and failed. The code must not depend on whether the failure came with
    # an explanation.
    result = CliResult.succeeded(verdict=verdict(provenance="solver", shortfalls=[]))

    assert result.exit_code is ExitCode.INFEASIBLE


def test_a_solved_feasible_verdict_exits_zero() -> None:
    result = CliResult.succeeded(verdict=verdict(provenance="solver", feasible=True, shortfalls=[]))

    assert result.exit_code is ExitCode.SUCCESS


def test_a_superseded_operation_this_invocation_dispatched_outranks_a_verdict() -> None:
    # The superseded solve produced no new plan, so the verdict on show is the old one. Nine names
    # what happened to the work this invocation asked for.
    result = CliResult.dispatched(
        operation(status="superseded", superseded_by=payloads.SUCCESSOR_ID), verdict=verdict()
    )

    assert result.exit_code is ExitCode.SUPERSEDED


def test_an_operation_this_invocation_only_read_does_not_decide_the_code() -> None:
    # A read that happens to see a week's operation reports it so a caller can follow it, and exits
    # by what the read found. A successful read must not report someone else's failure.
    seen = CliResult.succeeded(operation=operation(status="failed"))

    assert seen.exit_code is ExitCode.SUCCESS
    assert seen.operation is not None


def test_a_failed_operation_this_invocation_dispatched_exits_one() -> None:
    assert CliResult.dispatched(operation(status="failed")).exit_code is ExitCode.FAILURE


def test_an_operation_still_running_does_not_displace_the_verdict() -> None:
    result = CliResult.dispatched(operation(status="running"), verdict=verdict())

    assert result.exit_code is ExitCode.INFEASIBLE


def test_a_problem_outranks_everything_else() -> None:
    result = CliResult(
        ok=False,
        verdict=verdict(),
        operation=operation(status="superseded"),
        operation_was_dispatched=True,
        problem=cli_problem("syncr:cli-api-unreachable", "API unavailable", "no answer"),
    )

    assert result.exit_code is ExitCode.API_UNAVAILABLE
