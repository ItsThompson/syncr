"""The wire shapes the concession routes exchange.

Explicit schemas rather than mapped rows, so a column added to the table does not change the
contract by itself and the generated TypeScript changes only when this file does.

**A request names a kind and a target, and no figures.** The nights a reduction touches and the
minutes a breach takes come from the week's own verdict, which is what stops a caller asking for a
concession syncr did not offer. The field descriptions say so, because they reach the OpenAPI
document and therefore every caller.

**A concession is returned with its reductions keyed by date.** The wire spelling of a date is its
ISO form, which is the key the stored column, the frame occurrence, and the fold all use: one
spelling, so a client rendering "Tue, Wed and Thu" reads the same keys the server folded.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import ConfigDict, Field

from syncr_api.core.schemas import WireModel
from syncr_domain.plan import AdjustmentKind  # noqa: TC001 - pydantic resolves at runtime

if TYPE_CHECKING:
    from syncr_api.plans.records import WeekAdjustmentRecord

_KIND_DESCRIPTION = (
    "Which concession to solve against. One of the four the verdict panel offers: drop_item, "
    "reduce_routine, breach_floor, or accept_partial."
)
_TARGET_DESCRIPTION = (
    "What the concession acts on: a task for drop_item and accept_partial, a routine for "
    "reduce_routine, an Area for breach_floor. It must be one this week's verdict offers that "
    "kind for; anything else is a 422."
)
_REDUCTIONS_DESCRIPTION = (
    "Per-date minutes, for reduce_routine only, keyed by the local date the occurrence "
    "materializes on. Empty for the other three kinds. The enumerator chose the distribution, so "
    "this is the record of which nights the concession touched."
)
_DELTA_DESCRIPTION = (
    "How much this concession lowers the figure it names, in minutes: an increment against that "
    "figure as it stands rather than an absolute target. Set for breach_floor, null otherwise."
)


class TradeoffRequest(WireModel):
    """A request to solve one week against one concession. Persists nothing."""

    # An unknown field is refused rather than dropped, so a caller sending figures learns that the
    # figures are not theirs to choose instead of having them silently ignored.
    model_config = ConfigDict(extra="forbid")

    kind: AdjustmentKind = Field(description=_KIND_DESCRIPTION)
    target_id: UUID = Field(description=_TARGET_DESCRIPTION)


class AdjustmentResponse(WireModel):
    """One concession a week holds, as the verdict panel lists it."""

    id: UUID
    iso_week: str
    kind: AdjustmentKind
    target_id: UUID
    reductions: dict[str, int] = Field(default_factory=dict, description=_REDUCTIONS_DESCRIPTION)
    delta_minutes: int | None = Field(default=None, description=_DELTA_DESCRIPTION)
    created_at: datetime
    created_by_operation_id: UUID = Field(
        description="The operation whose proposal this concession was approved with."
    )

    @classmethod
    def of(cls, record: WeekAdjustmentRecord) -> Self:
        """One stored concession on the wire.

        Beside the shape rather than in a route module, because three surfaces render a
        concession: the week's own list, the approval that persisted one, and the revision that
        names the ones its plan was solved under.

        The minutes are narrowed here because the column is JSONB, which types its values as
        objects. What may be in it is a positive count of minutes and nothing else, which the
        write refuses anything but.
        """
        return cls(
            id=record.id,
            iso_week=str(record.iso_week),
            kind=record.kind,
            target_id=record.target_id,
            reductions={key: int(value) for key, value in record.reductions.items()},
            delta_minutes=record.delta_minutes,
            created_at=record.created_at,
            created_by_operation_id=record.created_by_operation_id,
        )


class AdjustmentsResponse(WireModel):
    """Every concession one week holds, in the order the assembler folds them."""

    adjustments: list[AdjustmentResponse]
