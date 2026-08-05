"""The wrapper: which of three readings decides the exit code, and in what order.

The order is the assertion. A problem is why the command failed, so it wins. An operation's terminal
status is what happened to the work that was dispatched, so it outranks the verdict of a plan that
work did not replace. An infeasible verdict is last, and it is not a failure.
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


def test_a_superseded_operation_outranks_an_infeasible_verdict() -> None:
    # The superseded solve produced no new plan, so the verdict on show is the old one. Nine names
    # what happened to the work.
    result = CliResult.succeeded(
        verdict=verdict(),
        operation=operation(status="superseded", superseded_by=payloads.SUCCESSOR_ID),
    )

    assert result.exit_code is ExitCode.SUPERSEDED


def test_an_operation_still_running_does_not_displace_the_verdict() -> None:
    result = CliResult.succeeded(verdict=verdict(), operation=operation(status="running"))

    assert result.exit_code is ExitCode.INFEASIBLE


def test_a_problem_outranks_everything_else() -> None:
    result = CliResult(
        ok=False,
        verdict=verdict(),
        operation=operation(status="superseded"),
        problem=cli_problem("syncr:cli-api-unreachable", "API unavailable", "no answer"),
    )

    assert result.exit_code is ExitCode.API_UNAVAILABLE
