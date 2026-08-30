"""promotion_declines: the one thing about a repeated-pin promotion that is stored

A promotion candidate is not a row. ``syncr_domain.promotion.detect_repeated_pins`` is one pass over
pin rows, and the weekly session runs it on every read, so the candidates are always as fresh as the
pins they are computed from. A table of them would be a cache of a computation nobody asked to
cache.

What cannot be recomputed is the reader's ANSWER. A declined candidate "does not
re-raise for a stated interval", and there was nothing for a decline to write.

| Column | Holds |
|---|---|
| ``promotion_id`` | ``PromotionRef.id``: the kind, the content, the weekday and the minute |
| ``declined_at`` | when the reader answered |
| ``suppressed_until`` | the instant the pattern may be raised again |

**The instant is stored rather than the interval.** The interval is configuration; what the reader
was told is that this will not be raised again until a particular moment, so that moment is the
fact. A row read under a later value of the configured interval would otherwise answer a different
question from the one the reader was told the answer to.

**One row per candidate, enforced by a unique index.** Declining twice is one answer given twice,
and two rows would leave which suppression is in force to read order. The write path upserts and
names this index as its conflict target.

The identity carries no week count, deliberately. A declined pattern that runs for a fourth week is
the same pattern, and an identity carrying the count would let the fourth week ask a question the
reader has already answered.

Every literal below is spelled here rather than imported. A revision describes the schema at its own
point in the chain and is replayed forever against databases at that point, so a value read from the
workspace's live code would describe the schema as it is now instead.

Revision ID: 0055_promotion_declines
Revises: 0051_conflict_commitments
Create Date: 2026-08-08

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0055_promotion_declines"
down_revision: str | None = "0051_conflict_commitments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "promotion_declines"
TENANT_ID = "tenant_id"
PROMOTION_ID = "promotion_id"

# What `PromotionRef.id` is at its longest: a kind, a UUID, a weekday and a minute of the day, with
# three separators. A longer value is refused by the route before it reaches a statement.
PROMOTION_ID_LENGTH = 96

ONE_DECLINE_PER_CANDIDATE_INDEX = f"uq_{TABLE}_{TENANT_ID}_{PROMOTION_ID}"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        # `PromotionRef.id`: the kind, the content, the weekday and the minute of the day. One value
        # because that is what a request carries and what a read compares, and because a row is
        # meaningless without all four parts.
        sa.Column(PROMOTION_ID, sa.String(length=PROMOTION_ID_LENGTH), nullable=False),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suppressed_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(TENANT_ID, sa.Uuid(), nullable=False),
        # A suppression that ended before it began would silence nothing while claiming to.
        sa.CheckConstraint(
            "declined_at < suppressed_until",
            name=op.f(f"ck_{TABLE}_suppression_ends_after_it_starts"),
        ),
        sa.ForeignKeyConstraint(
            [TENANT_ID],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_{TENANT_ID}_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    # One decline per candidate, so a second decline replaces the first rather than leaving which
    # suppression is in force to read order. It leads with the tenant, as every index here does.
    op.create_index(ONE_DECLINE_PER_CANDIDATE_INDEX, TABLE, [TENANT_ID, PROMOTION_ID], unique=True)


def downgrade() -> None:
    op.drop_index(ONE_DECLINE_PER_CANDIDATE_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
