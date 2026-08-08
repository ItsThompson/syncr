"""The one table: which promotion candidates a reader has declined, and until when.

**A decline is the only thing about a promotion that is stored.** Detection is one pass over pin
rows, so a candidate is what that pass answers rather than a row: there is nothing to persist, and a
table of candidates the session recomputes anyway would be a cache that has to be kept true. What
cannot be recomputed is the reader's answer, and that is what this holds.

**The row is keyed by the candidate's own group**, which is what ``PromotionRef.id`` renders. A
declined pattern that runs for a fourth week is the same pattern, so the identity carries no week
count and a fourth week does not re-ask a question that has been answered.

**One row per pattern, so a second decline replaces the first.** Declining twice is one answer given
twice, and two rows would leave which suppression is in force to read order. The unique index over
``(tenant_id, promotion_id)`` is what makes that structural, and the write path upserts against it.

``suppressed_until`` is stored rather than derived from ``declined_at`` plus a configured interval.
The interval is configuration, and a row read under a later value of it would answer a different
question from the one the reader was told: what they were told is that it will not be raised again
until a stated instant, so the instant is the fact.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.promotions.config import PROMOTION_DECLINES_TABLE, PROMOTION_ID_MAX_LENGTH

ONE_DECLINE_PER_CANDIDATE_INDEX = f"uq_{PROMOTION_DECLINES_TABLE}_{TENANT_ID_COLUMN}_promotion_id"


class PromotionDecline(Base, TenantScoped):
    """One promotion candidate the reader declined, and the instant it may be raised again."""

    __tablename__ = PROMOTION_DECLINES_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # `PromotionRef.id`: the kind, the content, the weekday and the minute of the day. Denormalized
    # as one value because that is what a request carries and what a read compares; the four parts
    # are never queried separately, and a row is meaningless without all four.
    promotion_id: Mapped[str] = mapped_column(String(PROMOTION_ID_MAX_LENGTH), nullable=False)
    declined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    suppressed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("declined_at < suppressed_until", name="suppression_ends_after_it_starts"),
        Index(ONE_DECLINE_PER_CANDIDATE_INDEX, TENANT_ID_COLUMN, "promotion_id", unique=True),
    )
