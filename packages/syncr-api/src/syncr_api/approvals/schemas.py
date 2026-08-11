"""The wire shape one approval answers with.

Flat rather than nesting the history's revision shape, because the two answer different questions:
the history lists what a week has been, and this says what one act just did. A client that wants
the revision beside its siblings reads the history route, which is where a revision is described.

**Both versions are on it, and that is ``PP5`` on the wire.** ``inputVersion`` is what the week
holds now, after this approval bumped it, and ``solvedAgainstVersion`` is the input state the
approved plan was produced from. A proposal may be approved while it is behind, so the two figures
differ exactly when the week moved on between the solve and the approval, and a client can see that
rather than having to infer it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import Field

# Runtime imports: pydantic resolves a field's annotation while the app is being built, so a
# nested model or a closed vocabulary named in one has to be importable then.
from syncr_api.concessions.schemas import AdjustmentResponse
from syncr_api.core.schemas import WireInstant, WireModel
from syncr_api.plans.config import RevisionReason  # noqa: TC001
from syncr_api.solving.schemas import OperationResponse

if TYPE_CHECKING:
    from syncr_api.approvals.service import ApprovedWeek


class WeekApprovedResponse(WireModel):
    """What one approval wrote, as the client redraws it."""

    revision_id: UUID = Field(description="The approved revision this appended, permanently.")
    iso_week: str
    reason: RevisionReason = Field(
        description="Which approval this was: user_approved, or tradeoff_approved when the "
        "proposal carried a concession. Decided by what the slot held, never by the caller."
    )
    approved_at: WireInstant = Field(description="When the user assented.")
    input_version: int = Field(
        description="The week's input version after this approval bumped it. A solve already "
        "running against the previous value fails its conditional write and is superseded."
    )
    solved_against_version: int = Field(
        description="The input version the approved plan was produced from. Lower than "
        "inputVersion by more than this approval's own bump when the week moved on while the "
        "proposal waited, which is permitted: the solve that mutation enqueued proposes any "
        "correction."
    )
    adjustment: AdjustmentResponse | None = Field(
        description="The concession this approval persisted, or null for an ordinary approval. "
        "The next solve of the week honors it without being asked again."
    )
    projection: OperationResponse = Field(
        description="The projection this approval enqueued, which is what writes the approved "
        "week to the user's calendar."
    )

    @classmethod
    def of(cls, approved: ApprovedWeek) -> Self:
        revision = approved.revision
        return cls(
            revision_id=revision.id,
            iso_week=str(revision.iso_week),
            reason=revision.reason,
            approved_at=approved.approved_at,
            input_version=approved.input_version,
            solved_against_version=revision.input_version,
            adjustment=(
                None if approved.adjustment is None else AdjustmentResponse.of(approved.adjustment)
            ),
            projection=OperationResponse.of(approved.projection),
        )
