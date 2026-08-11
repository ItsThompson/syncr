"""areas: drop the preference identifier nothing writes

An Area holds no preference identifier. A preference names its own owner, so ``preferences`` is
where that relation lives, and an Area's preference is addressed by the Area itself under
``/areas/{id}/preference``. The column was a second home for the relation: it carried no foreign
key, no writer ever filled it, and every row held null.

**The downgrade restores the column, not its values.** It was null on every row, so there is
nothing for a re-add to carry, and a value written into it after a downgrade would be a relation
no reader consults.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: drop_areas_default_preference
Revises: 0061_rejection_total
Create Date: 2026-08-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Named for what it
# does rather than numbered: the numeric prefixes before this one are not a sequence, so
# continuing them would either collide with a prefix already in the chain or imply an order the
# chain does not have. `down_revision` is what orders a revision.
revision: str = "drop_areas_default_preference"
down_revision: str | None = "0061_rejection_total"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "areas"
COLUMN = "default_preference_id"


def upgrade() -> None:
    op.drop_column(TABLE, COLUMN)


def downgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.Uuid(), nullable=True))
