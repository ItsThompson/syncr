"""verdict_events: rename the shortfall column so no reader totals it by accident

``verdict_events.shortfall_minutes`` held the LARGEST single gap of a verdict, never their sum.
The name invited exactly the wrong aggregate: ``SUM(shortfall_minutes)`` reads as a duration the
week is short by, but shortfalls can measure the same capacity twice -- a deadline gap and the
floor gap of the Area that deadline belongs to are one shortage seen two ways -- so the sum is not
a duration and can exceed the week itself.

The column is now ``largest_gap_minutes``, which states its own definition: a largest-of operator,
not an addable total. The episode ratio reads episode counts rather than this column, and nothing
else consumes it, so the rename is invisible to every metric.

A plain column rename carries both check constraints with it: Postgres rewrites the expressions
of constraints over a renamed column and keeps their names, so ``shortfall_is_not_negative`` and
``feasible_has_no_shortfall`` survive unchanged in both name and meaning.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: sr_plan_18_largest_gap
Revises: sr_intent_04_task_grid_floor
Create Date: 2026-09-15

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "sr_plan_18_largest_gap"
down_revision: str | None = "sr_intent_04_task_grid_floor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "verdict_events"
OLD = "shortfall_minutes"
NEW = "largest_gap_minutes"


def upgrade() -> None:
    op.alter_column(TABLE, OLD, new_column_name=NEW)


def downgrade() -> None:
    op.alter_column(TABLE, NEW, new_column_name=OLD)
