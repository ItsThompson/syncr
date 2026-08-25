"""tasks: the stored chunk bound states the floor the grid already implies.

The previous revision replaced ``min_chunk_minutes_is_a_duration`` with the multiple while
keeping the original ``BETWEEN 1`` lower bound, whose only content the multiple had absorbed.
This revision spells the floor the models declare, so a database at head carries the same
definition fresh-from-migrations and from-metadata, and autogenerate sees no drift. No scan
precedes it: the multiple is unchanged, and the multiple already refuses everything below one
step.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: sr_intent_04_task_grid_floor
Revises: sr_intent_04_task_grid
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "sr_intent_04_task_grid_floor"
down_revision: str | None = "sr_intent_04_task_grid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "tasks"

# Same name, stated definition: the floor is one step because the chunk is the smallest
# placement a splittable task may take, and every placement lands on the grid. ``op.f`` marks
# the name as final so the naming convention does not prefix it a second time on the drop.
DURATION_CHECK = "ck_tasks_min_chunk_minutes_is_a_duration"


def upgrade() -> None:
    op.drop_constraint(op.f(DURATION_CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(DURATION_CHECK),
        TABLE,
        "min_chunk_minutes BETWEEN 15 AND 10080 AND mod(min_chunk_minutes, 15) = 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(DURATION_CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(DURATION_CHECK),
        TABLE,
        "min_chunk_minutes BETWEEN 1 AND 10080 AND mod(min_chunk_minutes, 15) = 0",
    )
