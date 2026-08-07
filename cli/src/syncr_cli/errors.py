"""The failures a command raises, each carrying the problem it will be reported as.

A command raises; the runner renders. That is what lets human output, ``--json`` output, and
the exit code come from one object: the runner turns whatever was raised into a
:class:`~syncr_cli.results.CliResult` and asks the result for all three.

Every class here fixes a ``type`` and a ``title`` and takes the detail from its caller, which
is the same contract the api's own error hierarchy has. A detail that says only what broke
fails review: where a capability degraded, it names what still works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from syncr_cli.problems import (
    CLI_API_UNREACHABLE,
    CLI_FAILURE,
    CLI_MALFORMED_RESPONSE,
    CLI_NOT_AUTHENTICATED,
    CLI_TIMED_OUT,
    CLI_USAGE,
    Problem,
    cli_problem,
)

if TYPE_CHECKING:
    from syncr_cli.exit_codes import ExitCode
    from syncr_cli.wire.operation import Operation


class CliError(Exception):
    """A command's failure, reportable in either output format.

    The exit code is read off the problem rather than declared here, so one table maps every
    condition -- the api's and this package's -- onto a number.
    """

    problem_type: ClassVar[str]
    title: ClassVar[str]

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)

    @property
    def problem(self) -> Problem:
        """This failure as the problem details a caller reads."""
        return cli_problem(self.problem_type, self.title, self.detail)

    @property
    def exit_code(self) -> ExitCode:
        """What the process exits with when this failure is what happened."""
        return self.problem.exit_code


class UsageError(CliError):
    """A bad flag, a missing argument, or a value that names nothing."""

    problem_type = CLI_USAGE
    title = "Usage error"


class NotAuthenticated(CliError):
    """No stored refresh token, or one the Authorization Server no longer honors."""

    problem_type = CLI_NOT_AUTHENTICATED
    title = "Not authenticated"


class ApiUnreachable(CliError):
    """The API could not be reached at all: no connection, no answer, or no name."""

    problem_type = CLI_API_UNREACHABLE
    title = "API unavailable"


class MalformedResponse(CliError):
    """The API answered, and the answer is not the shape this command reads."""

    problem_type = CLI_MALFORMED_RESPONSE
    title = "Unreadable response"


class Failure(CliError):
    """A failure with no more specific class, reported as one rather than as a traceback."""

    problem_type = CLI_FAILURE
    title = "Command failed"


class WaitTimedOut(CliError):
    """A wait on an operation ran out before the operation reached a terminal status.

    Carries the operation as well as naming it in the detail, because the wait is resumable and an
    agent should not have to parse a sentence to resume it: the result this becomes reports the
    operation under the wrapper's own member, beside a ``problem`` saying the wait ended.
    """

    problem_type = CLI_TIMED_OUT
    title = "Timed out while waiting"

    def __init__(self, detail: str, *, operation: Operation) -> None:
        self.operation = operation
        super().__init__(detail)

    @property
    def operation_id(self) -> str:
        """The identifier a caller resumes the wait with."""
        return self.operation.id


class ApiRefused(CliError):
    """The API answered with problem details of its own, which are reported verbatim.

    The only subclass that states no ``problem_type`` or ``title``: it carries the api's problem
    rather than minting one, so a type of its own would be a value nothing reads and nothing maps.
    """

    def __init__(self, problem: Problem) -> None:
        self._problem = problem
        super().__init__(problem.detail)

    @property
    def problem(self) -> Problem:
        return self._problem
