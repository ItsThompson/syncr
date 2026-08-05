"""What an operation's terminal transition carries. Three values, one per way work ends.

The lifecycle's terminal step takes one of these rather than a status plus five optional
arguments, because each ending carries different facts and a signature holding all of them at
once cannot say which combinations are legal: a superseded operation has no error, a failure has
no result revision, and only a failure has inputs worth keeping.

``Superseded`` is not a failure and it is not an error. It is the expected outcome of editing
quickly -- the user's own later change displaced this solve, and a follow-up is already running --
so it is a member of its own here and it is reported with its own word and its own statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonDocument
    from syncr_domain.identifiers import OperationId, PlanRevisionId


@dataclass(frozen=True, slots=True)
class Succeeded:
    """The work completed and its result was adopted.

    ``result_revision_id`` is the revision this operation appended, and it is absent for the two
    kinds that append none: a calendar sync writes anchors and a projection writes a calendar.
    """

    result_revision_id: PlanRevisionId | None = None


@dataclass(frozen=True, slots=True)
class Superseded:
    """A later input state displaced this operation's result, so the result was discarded.

    ``superseded_by`` names the follow-up when one has been created. It is absent when the
    supersession is a pending operation being replaced, because the replacement is created after
    the row it replaces is closed.
    """

    superseded_by: OperationId | None = None


@dataclass(frozen=True, slots=True)
class Failed:
    """The work could not complete, and what still works.

    ``snapshot`` is the resolved inputs the attempt read. It is offered on every failure and kept
    only on the last one, because a retried attempt returns the operation to ``pending`` and the
    table forbids a snapshot on any status but ``failed``. What it buys is a production failure
    that reproduces locally: load the snapshot and call the solver. ``input_version`` cannot do
    that job -- it is a counter, so re-assembling against it yields current state rather than the
    state that failed.
    """

    code: str
    message: str
    snapshot: JsonDocument | None = None


type Outcome = Succeeded | Superseded | Failed
"""The three ways an operation ends. Widening this needs a branch in the lifecycle's dispatch."""
