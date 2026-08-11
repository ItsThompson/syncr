"""The wire shapes the two promotion routes answer with.

An accept answers with the ENTRY it moved, in the same shape the day-shape routes answer with, so a
client that already renders a template entry needs no second reading of one. A decline answers with
the two instants, because what the reader was told is when they will be asked again.
"""

from __future__ import annotations

# Runtime, not type-only: pydantic resolves a field annotation when the model is built.
from typing import TYPE_CHECKING, Self

from pydantic import Field

from syncr_api.core.schemas import WireInstant, WireModel
from syncr_api.promotions.config import DECLINE_SUPPRESSION_WEEKS
from syncr_api.templates.entry_schemas import TemplateEntryResponse

if TYPE_CHECKING:
    from syncr_api.promotions.records import PromotionDeclineRecord
    from syncr_api.promotions.service import AcceptedPromotion


class PromotionAcceptedResponse(WireModel):
    """What an accept changed: the day-shape entry, at the time the pattern named."""

    promotion_id: str = Field(description="The pattern that was absorbed.")
    template_id: str = Field(description="The day shape whose entry moved.")
    entry: TemplateEntryResponse = Field(
        description="The entry as it now stands. Its duration and its flex band are untouched: a "
        "promotion moves an entry and never resizes one."
    )
    statement: str = Field(
        description="What was changed, in the words a surface renders. Composed here so the screen "
        "and the CLI cannot describe one edit two ways."
    )

    @classmethod
    def of(cls, accepted: AcceptedPromotion, *, statement: str) -> Self:
        return cls(
            promotion_id=accepted.promotion_id,
            template_id=str(accepted.entry.template_id),
            entry=TemplateEntryResponse.of(accepted.entry),
            statement=statement,
        )


class PromotionDeclinedResponse(WireModel):
    """What a decline recorded: when it was answered, and until when it stays answered."""

    promotion_id: str = Field(description="The pattern that will not be raised again.")
    declined_at: WireInstant
    suppressed_until: WireInstant = Field(
        description="The instant the pattern may be raised again. Stored rather than derived, so "
        "the promise the reader was given is the fact that is kept."
    )
    suppression_weeks: int = Field(
        description="How many weeks that is, which is the interval the screen states."
    )
    statement: str = Field(description="What was recorded, in the words a surface renders.")

    @classmethod
    def of(cls, declined: PromotionDeclineRecord, *, statement: str) -> Self:
        return cls(
            promotion_id=declined.promotion_id,
            declined_at=declined.declined_at,
            suppressed_until=declined.suppressed_until,
            suppression_weeks=DECLINE_SUPPRESSION_WEEKS,
            statement=statement,
        )
