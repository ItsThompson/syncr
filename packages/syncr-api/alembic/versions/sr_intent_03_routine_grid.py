"""routines: the target time and both duration bounds owe the fifteen-minute grid.

A routine's span is declared, and every placement lands on the quarter-hour grid, so a stored
frame off the grid names a start or an end no block could hold. The domain refuses such a
declaration at the span; this revision gives the table the two check constraints that say the
same thing about what is stored: the target time lands on a quarter hour, and the target
duration and the elastic floor are whole steps.

**The revision refuses to run while any stored row is off the grid.** Nothing here snaps a
declaration a person authored onto the grid: moving a user's ``05:07`` to ``05:00`` without
assent would rewrite the frame they asked for. So the upgrade reads every row first, and if one
carries an off-grid value it raises, naming each offending row's identifier and every field of
that row that is off the grid. The operator fixes the data with the tenant's knowledge and
re-runs the one-shot; the constraint creation follows only on a clean reading.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: sr_intent_03_routine_grid
Revises: sr_deploy_03_operation_session
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "sr_intent_03_routine_grid"
down_revision: str | None = "sr_deploy_03_operation_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "routines"

TARGET_TIME_GRID_CHECK = "target_time_is_on_the_grid"
DURATIONS_GRID_CHECK = "durations_land_on_the_grid"

# The names the workspace's own naming convention renders for those constraints, which is what a
# database at this point in the chain actually holds and what the downgrade drops.
TARGET_TIME_GRID_CONSTRAINT = f"ck_{TABLE}_{TARGET_TIME_GRID_CHECK}"
DURATIONS_GRID_CONSTRAINT = f"ck_{TABLE}_{DURATIONS_GRID_CHECK}"

# The same readings the two constraints enforce, spelled as the scan that must come back clean
# before they are created, and as the SQL the constraints are created with.
_OFF_GRID_TARGET_TIME = (
    "mod(EXTRACT(MINUTE FROM target_time)::int, 15) <> 0 OR EXTRACT(SECOND FROM target_time) <> 0"
)
_OFF_GRID_DURATIONS = "mod(duration_minutes, 15) <> 0 OR mod(min_duration_minutes, 15) <> 0"

TARGET_TIME_GRID_SQL = (
    "mod(EXTRACT(MINUTE FROM target_time)::int, 15) = 0 AND EXTRACT(SECOND FROM target_time) = 0"  # noqa: E501
)
DURATIONS_GRID_SQL = "mod(duration_minutes, 15) = 0 AND mod(min_duration_minutes, 15) = 0"


def _refuse_off_grid_rows() -> None:
    """Name every stored row off the grid and every field of it that is, then stop."""
    bind = op.get_bind()
    rows = bind.execute(
        # TABLE and both clauses are module constants, so the interpolation names nothing a caller
        # controls.
        sa.text(
            f"SELECT id::text, target_time, duration_minutes, min_duration_minutes "  # noqa: S608
            f"FROM {TABLE} "
            f"WHERE {_OFF_GRID_TARGET_TIME} OR {_OFF_GRID_DURATIONS}"
        )
    ).mappings()

    named = []
    for row in rows:
        fields = []
        minute, second = row["target_time"].minute, row["target_time"].second
        if minute % 15 != 0 or second != 0:
            fields.append(f"target_time {row['target_time']}")
        if row["duration_minutes"] % 15 != 0:
            fields.append(f"duration_minutes {row['duration_minutes']}")
        if row["min_duration_minutes"] % 15 != 0:
            fields.append(f"min_duration_minutes {row['min_duration_minutes']}")
        named.append(f"{row['id']} ({', '.join(fields)})")

    if named:
        raise RuntimeError(
            "the routines table holds declarations off the fifteen-minute grid, so the "
            "constraint this revision adds has nothing true to say about them. Move each row "
            "onto the grid with its tenant's assent and re-run the migration; nothing was "
            f"snapped. Offending rows: {named}"
        )


def upgrade() -> None:
    _refuse_off_grid_rows()
    op.create_check_constraint(TARGET_TIME_GRID_CHECK, TABLE, TARGET_TIME_GRID_SQL)
    op.create_check_constraint(DURATIONS_GRID_CHECK, TABLE, DURATIONS_GRID_SQL)


def downgrade() -> None:
    op.drop_constraint(DURATIONS_GRID_CONSTRAINT, TABLE, type_="check")
    op.drop_constraint(TARGET_TIME_GRID_CONSTRAINT, TABLE, type_="check")
