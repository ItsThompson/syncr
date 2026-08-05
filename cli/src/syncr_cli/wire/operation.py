"""The ``Operation`` resource: what a command that dispatched work prints, and how a wait ends.

SSE is out of CLI scope by design, so long-running work is followed by polling this resource.
It was built to be pollable for exactly that reason.

**Three terminal statuses, three different codes, and that is the point.** A superseded
operation is not a failure: the user's own later edit displaced it and a follow-up is already
running, so it exits 9 and names its successor rather than exiting 1 and sending an agent to
re-dispatch. A wait that ran out exits 10 and prints the id, so the wait is resumable rather
than lost.

**An unrecognized status is refused rather than polled.** Treating a status this build does not
know as "not terminal yet" would turn a contract change into a wait that ends only at the
timeout, which reports the wrong thing about the work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from syncr_cli.errors import MalformedResponse
from syncr_cli.exit_codes import ExitCode
from syncr_cli.wire.reading import JsonMapping, integer, optional_nested, optional_text, text


class OperationStatus(StrEnum):
    """The state machine's five members, as the resource reports them."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


# Which statuses end a wait. Derived from the exit-code table below rather than listed twice, so
# a terminal status with no code, or a code for a status that cannot happen, is a type error
# rather than a wait that never ends.
EXIT_CODE_BY_TERMINAL_STATUS: dict[OperationStatus, ExitCode] = {
    OperationStatus.SUCCEEDED: ExitCode.SUCCESS,
    OperationStatus.FAILED: ExitCode.FAILURE,
    OperationStatus.SUPERSEDED: ExitCode.SUPERSEDED,
}

TERMINAL_STATUSES = frozenset(EXIT_CODE_BY_TERMINAL_STATUS)


@dataclass(frozen=True, slots=True)
class Operation:
    """One tracked long-running job, as a client follows it."""

    id: str
    kind: str
    status: OperationStatus
    statement: str
    attempt: int
    superseded_by: str | None
    error_message: str | None
    payload: JsonMapping

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(
            id=text(payload, "id", path),
            kind=text(payload, "kind", path),
            status=_status(payload, path),
            statement=text(payload, "statement", path),
            attempt=integer(payload, "attempt", path),
            superseded_by=optional_text(payload, "supersededBy", path),
            error_message=_error_message(payload, path),
            payload=payload,
        )

    @property
    def is_terminal(self) -> bool:
        """Whether this operation has stopped moving."""
        return self.status in TERMINAL_STATUSES

    @property
    def exit_code(self) -> ExitCode:
        """The code a completed wait on this operation exits with.

        Non-terminal reads as success: a command that dispatched work and did not wait has done
        exactly what it was asked, and the operation id is in its output.
        """
        return EXIT_CODE_BY_TERMINAL_STATUS.get(self.status, ExitCode.SUCCESS)

    @property
    def summary(self) -> str:
        """What a human reads about this operation: its own sentence, and what to follow.

        The statement is the server's, because supersession and failure are worded there and a
        second wording is a second story about one row.
        """
        lines = [f"{self.kind} {self.id}  {self.status.value}", f"  {self.statement}"]
        if self.superseded_by is not None:
            lines.append(f"  superseded by {self.superseded_by}")
        if self.error_message is not None:
            lines.append(f"  {self.error_message}")
        if self.attempt > 1:
            lines.append(f"  attempt {self.attempt}")
        return "\n".join(lines)


def _status(payload: JsonMapping, path: str) -> OperationStatus:
    raw = text(payload, "status", path)
    try:
        return OperationStatus(raw)
    except ValueError as error:
        named = ", ".join(member.value for member in OperationStatus)
        raise MalformedResponse(
            f"{path}.status is {raw!r}, and an operation is in one of: {named}. This CLI will "
            "not wait on a status it cannot recognize as finished."
        ) from error


def _error_message(payload: JsonMapping, path: str) -> str | None:
    failure = optional_nested(payload, "error", path)
    if failure is None:
        return None
    return f"{text(failure, 'code', f'{path}.error')}: {text(failure, 'message', f'{path}.error')}"
