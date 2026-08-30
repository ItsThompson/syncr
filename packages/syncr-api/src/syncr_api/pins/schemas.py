"""The wire shapes the pin routes take and answer with.

``PinnedResponse`` is the ``PinResponse``: the pin, the verdict, and the operation, which
is everything a client needs to redraw once. The verdict shape is the plan package's, because that
shape crosses the wire from the week view and from a tradeoff request too: a second declaration of
it is how two surfaces would come to render one verdict differently.

**A pin carries both halves of its counterfactual**, because that is what a pin is for: the
reason panel renders an ``instead of`` clause and a ``cost`` reading from the pin itself rather than
by walking the edit log.

**Every duration is integer minutes and every instant is an instant**, which is this api's own
convention throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import Field

from syncr_api.core.schemas import WireInstant, WireModel, WireSpan, WireText
from syncr_api.plans.verdict_schemas import VerdictResponse
from syncr_api.solving.schemas import OperationResponse

if TYPE_CHECKING:
    from syncr_api.pins.service import PinnedWeek
    from syncr_api.plans.records import PinRecord


class PinCreateRequest(WireModel):
    """One drag, one keyboard move, or the ``p`` toggle."""

    block_id: WireText = Field(
        description="The block being pinned, as the week view spells its id.",
        min_length=1,
    )
    start: WireInstant = Field(
        description="Where the block now begins. Its length is unchanged, because a drag moves and "
        "does not resize, so the pinned span is this instant plus the block's own duration."
    )


class RejectBlockRequest(WireModel):
    """One proposed move the user refuses."""

    block_id: WireText = Field(
        description="The block the pending proposal would move. Rejecting the move pins the block "
        "at the placement the plan of record already holds it at.",
        min_length=1,
    )


class PinResponse(WireModel):
    """One pin: where the user put a block, what the solver had chosen, and what that cost."""

    id: UUID
    iso_week: str = Field(
        description="The one week this pin constrains. Pins do not carry forward."
    )
    block_id: str = Field(description="The block this pin holds, as the week view spells its id.")
    interval: WireSpan = Field(description="Where the user put it.")
    superseded_placement: WireSpan = Field(description="Where the solver had put it.")
    objective_delta: float | None = Field(
        description="What the user's choice cost in objective units, under weightSetVersion. "
        "Positive when the user's placement is worse under those weights, and zero for a pin that "
        "keeps a block where it already is."
    )
    weight_set_version: int = Field(
        description="The weight set the cost was measured under. Stored rather than recomputed, "
        "because the weights it was priced against will have moved on."
    )
    created_at: WireInstant = Field(description="When the user made this edit.")

    @classmethod
    def of(cls, record: PinRecord) -> Self:
        """The wire shape of one stored pin."""
        return cls(
            id=record.id,
            iso_week=str(record.iso_week),
            block_id=record.block_id,
            interval=WireSpan.of(record.interval),
            superseded_placement=WireSpan.of(record.superseded_placement),
            objective_delta=record.objective_delta,
            weight_set_version=record.weight_set_version,
            created_at=record.created_at,
        )


class PinnedResponse(WireModel):
    """What one edit answers with: the pin, the live verdict, and the solve to follow.

    Three fields because a client redraws all three on the same frame. The verdict is computed
    synchronously from capacity arithmetic and requires no solve to complete, which is what makes
    that one redraw possible; the operation is what says when the unpinned remainder has reflowed.
    """

    pin: PinResponse
    verdict: VerdictResponse = Field(
        description="The week's verdict as of this edit, from the capacity probe. Its provenance "
        "says so: arithmetic proves infeasibility and never feasibility."
    )
    operation: OperationResponse = Field(
        description="The solve this edit asked for, due one debounce window later, or the one "
        "already in flight that this edit joined."
    )

    @classmethod
    def of(cls, pinned: PinnedWeek) -> Self:
        """The wire shape of one edit's answer."""
        return cls(
            pin=PinResponse.of(pinned.pin),
            verdict=VerdictResponse.of(pinned.verdict),
            operation=OperationResponse.of(pinned.operation),
        )


class PinReleased(WireModel):
    """What a release answers with, so a retried release replays rather than 404ing.

    The route responds ``204`` and this body never reaches the wire. It exists because the
    idempotency guard stores and replays a response MODEL, and a release has no other shape to
    store: without it, a retry with the same key would find the pin already gone.
    """

    released: Literal[True] = True
