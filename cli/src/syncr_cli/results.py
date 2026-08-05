"""``CliResult``: the one shape every command answers with, in either format.

```
interface CliResult<T> {
  ok: boolean;
  data: T | null;
  verdict: Verdict | null;    // present whenever the command changed the plan
  operation: Operation | null; // present when the command dispatched work, or read one in flight
  problem: Problem | null;     // present when ok is false
}
```

Five members, identical across every command, so an agent writes one parser and branches on
shape rather than parsing prose.

**Human output, ``--json`` output, and the exit code all come from this object.** That is what
makes it impossible for them to disagree: a command builds one result and returns it, and the
runner renders it twice and exits with the number it asks for.

**Only work this invocation dispatched decides the exit code.** An operation a command merely read
is reported so a caller can follow it, and a read that saw someone else's failing solve still exits
by what the read found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syncr_cli.exit_codes import ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from syncr_cli.problems import Problem
    from syncr_cli.wire.operation import Operation
    from syncr_cli.wire.reading import JsonMapping
    from syncr_cli.wire.verdict import Verdict

# How a surface renders an instant a verdict names. A week's ledger holds the zone map and can
# print `Fri 09:00`; a surface without one prints the instant itself.
type DeadlineRenderer = Callable[[datetime], str]


class Rendered(Protocol):
    """A command's payload, in both renderings.

    ``payload`` is what ``--json`` emits and the two line groups are what a terminal shows. Both
    come off one object, which is the whole reason the protocol carries them together.

    **The verdict sits between the two groups.** The week's ledger prints its heading and its
    summary strip, then the verdict, then the day rows, and a renderer that appended the verdict
    after everything could not produce that shape. Two groups rather than one flag, so no view
    can forget to print a verdict: the renderer places it, always.
    """

    @property
    def payload(self) -> JsonMapping:
        """This payload as the object ``--json`` carries under ``data``."""
        ...

    def header_lines(self) -> list[str]:
        """The lines a terminal shows above the verdict."""
        ...

    def body_lines(self) -> list[str]:
        """The lines a terminal shows below the verdict. Empty where a payload has no body."""
        ...

    def render_deadline(self, moment: datetime) -> str:
        """How this payload's surface prints an instant a verdict's shortfall names."""
        ...


@dataclass(frozen=True, slots=True)
class CliResult:
    """What one command did, and everything three renderings need to say so."""

    ok: bool
    data: Rendered | None = None
    verdict: Verdict | None = None
    operation: Operation | None = None
    problem: Problem | None = None
    # Whether the operation is work this invocation asked for rather than one it merely read. A read
    # that happens to see a week's in-flight solve reports it, and must not exit by its status: the
    # command succeeded, and the status belongs to work nobody here asked for. The two classmethods
    # below are how a command states this; nothing else should set it.
    operation_was_dispatched: bool = False

    @classmethod
    def succeeded(
        cls,
        data: Rendered | None = None,
        *,
        verdict: Verdict | None = None,
        operation: Operation | None = None,
    ) -> CliResult:
        """A command that did what it was asked. It may still exit non-zero.

        Any operation here is informational: it is reported so a caller can follow it, and it does
        not decide the exit code.
        """
        return cls(ok=True, data=data, verdict=verdict, operation=operation)

    @classmethod
    def dispatched(
        cls,
        operation: Operation,
        *,
        data: Rendered | None = None,
        verdict: Verdict | None = None,
    ) -> CliResult:
        """A command that dispatched work, or waited on work it dispatched.

        The operation's terminal status is the outcome of what this invocation asked for, so it
        decides the exit code: 0, 1, or 9 naming the successor.
        """
        return cls(
            ok=True,
            data=data,
            verdict=verdict,
            operation=operation,
            operation_was_dispatched=True,
        )

    @classmethod
    def failed(cls, problem: Problem) -> CliResult:
        """A command that did not."""
        return cls(ok=False, problem=problem)

    @property
    def exit_code(self) -> ExitCode:
        """The number this result exits with.

        Three readings in order, and the order is what each one means. A problem is why the
        command failed, so it wins. An operation this invocation dispatched outranks the verdict of
        the plan that work did not replace. An infeasible verdict is last and is not a failure: the
        command succeeded and the week cannot hold its commitments.
        """
        if self.problem is not None:
            return self.problem.exit_code
        if self.operation_was_dispatched and self.operation is not None:
            dispatched = self.operation.exit_code
            if dispatched is not ExitCode.SUCCESS:
                return dispatched
        if self.verdict is not None and self.verdict.is_infeasible:
            return ExitCode.INFEASIBLE
        return ExitCode.SUCCESS
