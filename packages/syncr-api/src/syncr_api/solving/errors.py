"""What a refused operation transition raises, and why the pair of types exists.

An operation's status is written by the lifecycle and by nothing else, and every step it takes is
one the state machine names. A step that applies to no row is one of two things, and a caller
usually knows which:

``OperationNotFound`` is a row that is not this tenant's. Nothing races that into existence, so it
is always a defect in the caller.

``OperationMovedOn`` is a row that exists and holds a status the attempted step cannot leave. For a
caller that had just read the row as steppable -- the reaper, and the solve coordinator's claim scan
-- that is a **lost race**: something else stepped it in between, which is expected under
concurrency and is a skip rather than a failure. For a caller that asked for a step the machine
never had from that status, it is a defect.

**The exception cannot tell those two apart and does not pretend to.** What it carries is the pair
the caller needs to decide: the status the row actually held, and the status that was attempted. A
caller that read the row in the same transaction knows what it expected, so the discrimination lives
where that knowledge is. The reaper treats it as a lost race because it had just read the row as
``running``; a defect there would mean the machine itself is wrong, which its own suite covers.

Neither is part of the error vocabulary a service raises. Both render as the generic 500 the
catch-all handler produces when they reach a request, and the fault is logged there."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_api.solving.config import OperationStatus
    from syncr_domain.identifiers import OperationId


class IllegalTransition(Exception):
    """A step that applied to no row, carrying what the row held and what was attempted."""

    def __init__(
        self,
        message: str,
        *,
        operation_id: OperationId,
        held: OperationStatus | None,
        attempted: OperationStatus,
    ) -> None:
        super().__init__(message)
        self.operation_id = operation_id
        self.held = held
        self.attempted = attempted


class OperationNotFound(IllegalTransition):
    """No row of this tenant. ``held`` is ``None``, and this is always a caller defect."""


class OperationMovedOn(IllegalTransition):
    """The row holds a status this step cannot leave: a lost race, or a step that never existed."""
