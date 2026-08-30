"""A proposal on the wire: the changes waiting for assent, and the slot they are held in.

The ``ProposalDiff``, and it is what the grid renders proposal targets from: a target draws
with no fill plus a dashed outline, which is the only state without a fill, so the client needs the
placement the plan WANTS and the one it would replace.

**Which list a change is in is what kind of change it is**, on the wire exactly as in the domain. So
there is no ``kind`` field: an addition has no ``before``, a removal has no ``after``, and a move
has both and they differ. A field beside the three lists could only contradict them, and the value
type these are built from refuses a change that disagrees with its list, so a client may read the
pair of placements from the list it arrived in.

**``blockId`` is derived and is still on the wire**, for the reason a block's is: it is a digest of
the week and the binding, and it is what the grid pairs a proposed change with a rendered block on.
Nothing on the client composes one.

**Every instant is an instant and every duration is integer minutes**, which is this api's own
convention throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import Field

# Runtime imports, every one of them: pydantic resolves a field's annotation while the app is being
# built, so a nested model named in one has to be importable then.
from syncr_api.concessions.schemas import AdjustmentResponse
from syncr_api.core.schemas import WireInstant, WireModel, WireSpan
from syncr_api.plans.clause_schemas import ReasonResponse
from syncr_api.plans.document_schemas import BindingResponse
from syncr_api.plans.verdict_schemas import VerdictResponse

if TYPE_CHECKING:
    from syncr_api.plans.week_views import PendingProposal
    from syncr_domain.proposals import BlockChange, ProposalDiff


class BlockChangeResponse(WireModel):
    """One block a candidate plan wants to add, drop, or move, and why."""

    block_id: str = Field(
        description="The block this change names, a digest of the week and the binding, so it "
        "pairs with a rendered block without the client composing one."
    )
    binding: BindingResponse = Field(
        description="What the block's content IS. Travels with the change because a change is "
        "stated over the identity rather than over the digest."
    )
    title: str
    area_id: UUID | None = Field(
        description="The Area this block is charged to. Null for the frame and for an imported "
        "commitment."
    )
    reason: ReasonResponse = Field(
        description="Why the CANDIDATE wants this change. For a removal there is no candidate "
        "block, so it is the last thing the live plan said about the block it is dropping."
    )
    before: WireSpan | None = Field(
        description="Where the live plan holds this block. Null for an addition, which replaces "
        "nothing."
    )
    after: WireSpan | None = Field(
        description="Where the candidate wants it. Null for a removal, which wants nowhere."
    )

    @classmethod
    def of(cls, change: BlockChange) -> Self:
        return cls(
            block_id=change.block_id,
            binding=BindingResponse.of(change.binding),
            title=change.title,
            area_id=change.area_id,
            reason=ReasonResponse.of(change.reason),
            before=None if change.before is None else WireSpan.of(change.before),
            after=None if change.after is None else WireSpan.of(change.after),
        )


class ProposalDiffResponse(WireModel):
    """The assent-requiring changes between the plan of record and a candidate plan.

    Three lists, and one block appears in exactly one of them: two changes naming one block would
    leave the reader to decide which of them the plan is proposing, and it proposes one thing per
    block.
    """

    added: list[BlockChangeResponse] = Field(
        description="Blocks the candidate wants to put somewhere they displace something. An "
        "addition into free time needs no assent and is applied rather than proposed."
    )
    removed: list[BlockChangeResponse] = Field(
        description="Blocks the candidate wants to drop. syncr may add without asking and may "
        "never remove without asking."
    )
    moved: list[BlockChangeResponse] = Field(
        description="Blocks the candidate wants elsewhere. Both placements are carried and they "
        "differ: a move that leaves a block where it is is not a change at all."
    )

    @classmethod
    def of(cls, diff: ProposalDiff) -> Self:
        return cls(
            added=[BlockChangeResponse.of(one) for one in diff.added],
            removed=[BlockChangeResponse.of(one) for one in diff.removed],
            moved=[BlockChangeResponse.of(one) for one in diff.moved],
        )


class PendingProposalResponse(WireModel):
    """The proposal a week is holding, as its own route answers with it.

    **The candidate plan document is deliberately absent.** A proposal IS the difference between
    the plan of record and a candidate, and that difference is what the grid renders: the live plan
    is already on the week view this route sits beside, so carrying the whole candidate week would
    put a second document in a payload whose reader has one.
    """

    iso_week: str
    proposal: ProposalDiffResponse = Field(
        description="What is waiting for assent. Empty in all three lists is possible and means "
        "the solve found nothing that needed asking about."
    )
    verdict: VerdictResponse = Field(
        description="What the solve that produced this proposal proved about the week. Its "
        "provenance is solver, because an attempted placement knows the answer."
    )
    candidate_adjustment: AdjustmentResponse | None = Field(
        description="The concession this proposal was solved under, or null for an ordinary "
        "proposal. It is not persisted until the proposal is approved, and it carries the "
        "identifier the approval will persist it under."
    )
    input_version: int = Field(
        description="The input state this proposal was SOLVED against. Lower than the week's own "
        "when the week moved on while the proposal waited, which is permitted: approval is never "
        "blocked, and the solve that mutation enqueued proposes any correction."
    )
    weight_set_version: int = Field(
        description="The weight set that produced the candidate document, carried because an "
        "approved revision says which weights produced its plan."
    )
    operation_id: UUID = Field(description="The solve that put this proposal in the slot.")
    created_at: WireInstant = Field(description="When that solve landed.")

    @classmethod
    def of(cls, held: PendingProposal) -> Self:
        return cls(
            iso_week=str(held.iso_week),
            proposal=ProposalDiffResponse.of(held.diff),
            verdict=VerdictResponse.of(held.verdict),
            candidate_adjustment=(
                None
                if held.candidate_adjustment is None
                else AdjustmentResponse.of(held.candidate_adjustment)
            ),
            input_version=held.input_version,
            weight_set_version=held.weight_set_version,
            operation_id=held.operation_id,
            created_at=held.created_at,
        )
