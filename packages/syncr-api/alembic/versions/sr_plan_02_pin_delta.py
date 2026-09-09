"""pins: require the objective delta every held row carries

No backfill runs. Before this revision, ``hold`` and ``price`` ran in one transaction, so no
committed row can carry a null delta.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: sr_plan_02_pin_delta
Revises: sr_plan_20_charged_misses
Create Date: 2026-08-25

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "sr_plan_02_pin_delta"
down_revision: str | None = "sr_plan_20_charged_misses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "pins"
COLUMN = "objective_delta"


def upgrade() -> None:
    op.alter_column(TABLE, COLUMN, nullable=False)


def downgrade() -> None:
    op.alter_column(TABLE, COLUMN, nullable=True)
