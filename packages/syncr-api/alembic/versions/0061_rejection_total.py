"""rejection_total: how many components a read refused, beside the sample it kept

``calendar_sources.rejections`` holds the components one attempt refused, as JSONB, read whole on
every panel render. A publisher decides how many components a feed holds, so the stored list is a
bounded sample per rejection kind rather than all of them, and the count a panel reports cannot be
that list's length: a feed refusing fifty thousand components would report fifteen.

So the count is a column of its own. It is not derived from the list, in either direction:

- a ``jsonb_array_length`` read would report the sample size, which is the defect;
- and the sample cannot be reconstructed from the count.

**Every row that already exists takes the length of its own list.** That is the true count for those
rows, because nothing bounded the list when they were written, and it is the only figure the row
carries. A default of zero would report a stored panel's rejections as never having happened.

Every literal below is spelled here rather than imported. A revision describes the schema at its own
point in the chain and is replayed forever against databases at that point, so a value read from the
workspace's live code would describe the schema as it is now instead.

Revision ID: 0061_rejection_total
Revises: 0055_promotion_declines
Create Date: 2026-08-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0061_rejection_total"
down_revision: str | None = "0055_promotion_declines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "calendar_sources"
SAMPLE = "rejections"
TOTAL = "rejected_total"

# The name the model states. The metadata's naming convention turns it into
# `ck_calendar_sources_counts_are_not_negative`, and alembic applies that convention here too, so
# the prefix belongs to the convention rather than to this constant.
COUNTS_ARE_NOT_NEGATIVE = "counts_are_not_negative"

# The count a pre-existing row takes: the length of the list it already carries. Published as a
# constant so the statement a test drives is the statement this revision runs, rather than a copy of
# it that can drift. Every name interpolated is a literal declared above, so nothing here composes a
# statement out of a value.
DERIVED_FROM_THE_SAMPLE = (
    f"UPDATE {TABLE} SET {TOTAL} = jsonb_array_length({SAMPLE}) WHERE {SAMPLE} IS NOT NULL"  # noqa: S608
)

# The two counts this table already held, and the new one. Restated rather than altered in place:
# Postgres has no way to add a conjunct to a check constraint.
_PREVIOUS_COUNTS = "events_read >= 0 AND anchors_current >= 0"
_EVERY_COUNT = f"{_PREVIOUS_COUNTS} AND {TOTAL} >= 0"


def upgrade() -> None:
    # A server default so the NOT NULL holds for the rows that already exist, then dropped, because
    # the model states the default on the Python side and a default left here would be schema the
    # model does not describe.
    op.add_column(TABLE, sa.Column(TOTAL, sa.Integer(), nullable=False, server_default="0"))
    op.execute(DERIVED_FROM_THE_SAMPLE)
    op.alter_column(TABLE, TOTAL, server_default=None)
    op.drop_constraint(COUNTS_ARE_NOT_NEGATIVE, TABLE, type_="check")
    op.create_check_constraint(COUNTS_ARE_NOT_NEGATIVE, TABLE, _EVERY_COUNT)


def downgrade() -> None:
    op.drop_constraint(COUNTS_ARE_NOT_NEGATIVE, TABLE, type_="check")
    op.create_check_constraint(COUNTS_ARE_NOT_NEGATIVE, TABLE, _PREVIOUS_COUNTS)
    op.drop_column(TABLE, TOTAL)
