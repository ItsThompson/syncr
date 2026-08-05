"""The process's twelve answers, and the table ``--help`` prints.

An AI agent branches on this number before it reads a byte of output, so the set is closed,
each member means one thing, and the summary a member carries is the summary the help text
renders. One definition, so the table cannot drift from the code that returns it.

Three members exist because collapsing them into :data:`ExitCode.FAILURE` would make an
agent treat three normal outcomes as errors. An infeasible week is the product working
correctly, a superseded solve is the expected result of editing quickly, and a wait that ran
out of patience says nothing about the work it was waiting on.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """What the process exits with, and what each number claims."""

    SUCCESS = 0
    FAILURE = 1
    USAGE = 2
    NOT_AUTHENTICATED = 3
    INSUFFICIENT_SCOPE = 4
    NOT_FOUND = 5
    CONFLICT = 6
    VALIDATION_FAILED = 7
    INFEASIBLE = 8
    SUPERSEDED = 9
    TIMED_OUT = 10
    API_UNAVAILABLE = 11

    @property
    def summary(self) -> str:
        """What this code tells a caller, in the words the help table prints."""
        return _SUMMARIES[self]


# Beside the enum rather than inside it, because a member of an IntEnum whose value is a
# string is a second member. Keyed by the member, so a new code with no summary is a
# KeyError at first read rather than a blank row in the table.
_SUMMARIES: dict[ExitCode, str] = {
    ExitCode.SUCCESS: "success",
    ExitCode.FAILURE: "generic failure",
    ExitCode.USAGE: "usage error: bad flag, missing argument, malformed value",
    ExitCode.NOT_AUTHENTICATED: "not authenticated, or the refresh token is invalid",
    ExitCode.INSUFFICIENT_SCOPE: "authenticated but insufficient scope",
    ExitCode.NOT_FOUND: "not found",
    ExitCode.CONFLICT: "conflict: an off-plan overlap, a second write target, a cleared proposal",
    ExitCode.VALIDATION_FAILED: "validation failure: a minimum chunk above an estimate",
    ExitCode.INFEASIBLE: "INFEASIBLE. The command succeeded and the week cannot hold its "
    "commitments",
    ExitCode.SUPERSEDED: "operation superseded: a later edit displaced it, and it names its "
    "successor",
    ExitCode.TIMED_OUT: "operation timed out while waiting. Distinct from a failure",
    ExitCode.API_UNAVAILABLE: "the API is unavailable",
}

EXIT_CODE_TABLE_HEADING = "exit codes:"


def exit_code_table() -> str:
    """Every code and its summary, as ``--help`` prints it on every command.

    Right-aligned on the number so the column is comparable by eye, which is the same
    discipline the ledger's durations follow.
    """
    return "\n".join(
        [EXIT_CODE_TABLE_HEADING, *(f"  {code.value:>2}  {code.summary}" for code in ExitCode)]
    )
