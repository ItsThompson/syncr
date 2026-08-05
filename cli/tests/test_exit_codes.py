"""The exit-code vocabulary, asserted against the enum rather than against a list.

A hand-maintained list of codes beside the enum would be a second inventory, and the moment the
enum grew the list would be the one a reader believed. So every assertion here is bounded by
``ExitCode`` itself: a new member with no summary, no row in the table, or nothing that can
produce it fails a test rather than shipping.
"""

from __future__ import annotations

import pytest

from syncr_cli.exit_codes import EXIT_CODE_TABLE_HEADING, ExitCode, exit_code_table
from syncr_cli.problems import EXIT_CODE_BY_PROBLEM_TYPE

# The three codes no problem produces, because none of them is a failure. Zero is success; an
# infeasible week and a superseded solve are outcomes a successful command reports.
CODES_FROM_A_SUCCESSFUL_RESULT = frozenset(
    {ExitCode.SUCCESS, ExitCode.INFEASIBLE, ExitCode.SUPERSEDED}
)


def test_the_codes_are_the_twelve_the_documentation_states() -> None:
    assert [int(code) for code in ExitCode] == list(range(12))


@pytest.mark.parametrize("code", list(ExitCode))
def test_every_code_carries_the_summary_its_help_table_prints(code: ExitCode) -> None:
    assert code.summary.strip()


def test_the_table_holds_one_row_per_code_and_nothing_else() -> None:
    lines = exit_code_table().splitlines()

    assert lines[0] == EXIT_CODE_TABLE_HEADING
    assert len(lines) == len(ExitCode) + 1
    for code, line in zip(ExitCode, lines[1:], strict=True):
        assert line.endswith(code.summary)
        assert line.split()[0] == str(int(code))


def test_the_table_right_aligns_the_number_so_the_column_reads_down() -> None:
    # Ten and eleven are two digits and the rest are one, so an unaligned table would put the
    # summaries of the first ten in a different column from the last two.
    columns = {line.index(code.summary) for code, line in _rows()}

    assert len(columns) == 1


def test_every_code_has_something_that_can_produce_it() -> None:
    # The guard the vocabulary needs: a code nothing maps onto is a code an agent can never see,
    # and a documented one it can never see is worse than no documentation.
    producible = set(EXIT_CODE_BY_PROBLEM_TYPE.values()) | CODES_FROM_A_SUCCESSFUL_RESULT

    assert producible == set(ExitCode)


def test_the_three_normal_outcomes_are_not_the_generic_failure() -> None:
    # Collapsing these would make an agent treat three normal outcomes as errors.
    assert (
        len({ExitCode.INFEASIBLE, ExitCode.SUPERSEDED, ExitCode.TIMED_OUT, ExitCode.FAILURE}) == 4
    )


def _rows() -> list[tuple[ExitCode, str]]:
    return list(zip(ExitCode, exit_code_table().splitlines()[1:], strict=True))
