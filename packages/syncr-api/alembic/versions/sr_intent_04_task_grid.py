"""tasks: the minimum chunk owes the fifteen-minute grid.

A task's minimum chunk is the smallest placement a splittable task may take, and every
placement lands on the quarter-hour grid, so a stored chunk off the grid names a length no
block could hold. The domain refuses such a declaration beside T1; this revision gives the
``min_chunk_minutes_is_a_duration`` constraint the multiple that says the same thing about
what is stored.

**The revision refuses to run while any stored row is off the grid.** Nothing here snaps a
value a person authored onto the grid: moving a stored 25-minute chunk to 15 or 30 without
assent would rewrite the physics they asked for. So the upgrade reads every row first, and if
one carries an off-grid chunk it raises, naming each offending row's identifier and field. The
operator fixes the data with the tenant's knowledge and re-runs the one-shot; the constraint
replacement follows only on a clean reading.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: sr_intent_04_task_grid
Revises: sr_intent_03_routine_grid
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "sr_intent_04_task_grid"
down_revision: str | None = "sr_intent_03_routine_grid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "tasks"

# The constraint keeps its name: it still says the stored chunk is a duration. What changes is
# that a duration now means a whole number of steps. ``op.f`` marks the name as final, so the
# naming convention does not prefix it a second time on the drop.
DURATION_CHECK = "ck_tasks_min_chunk_minutes_is_a_duration"

# The same readings the replaced constraints enforce, spelled as the scan that must come back
# clean before the new one is created.
_ON_GRID_CHUNK = "mod(min_chunk_minutes, 15) = 0"


def _refuse_off_grid_rows() -> None:
    """Name every stored row whose minimum chunk is off the grid, then stop."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"SELECT id::text, min_chunk_minutes FROM {TABLE} "  # noqa: S608
            f"WHERE NOT ({_ON_GRID_CHUNK})"
        )
    ).mappings()

    named = [f"{row['id']} (min_chunk_minutes {row['min_chunk_minutes']})" for row in rows]
    if named:
        raise RuntimeError(
            "the tasks table holds minimum chunks off the fifteen-minute grid, so the "
            "constraint this revision leaves behind has nothing true to say about them. Move "
            "each row onto the grid with its tenant's assent and re-run the migration; nothing "
            f"was snapped. Offending rows: {named}"
        )


def upgrade() -> None:
    _refuse_off_grid_rows()
    op.drop_constraint(op.f(DURATION_CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(DURATION_CHECK),
        TABLE,
        "min_chunk_minutes BETWEEN 1 AND 10080 AND mod(min_chunk_minutes, 15) = 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(DURATION_CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(DURATION_CHECK),
        TABLE,
        "min_chunk_minutes BETWEEN 1 AND 10080",
    )
