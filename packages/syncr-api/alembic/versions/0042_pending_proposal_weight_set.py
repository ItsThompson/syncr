"""pending proposals: the weight set that produced the document in the slot

``plan_revisions.weight_set_version`` is ``NOT NULL`` and says which weights produced the plan.
Approval appends a revision FROM the pending slot, and the slot carried no such column, so the
approved revision had nowhere to read it from. The two answers available without this column are
both wrong: the weight set in force at approval names whichever set the user activated since the
solve, and a placeholder claims a version that produced nothing.

So the slot records it, from the same solve that produced its document. The column is written by
the one path that fills the slot, which already holds the figure: the adoption reads it off the
same operation's load.

**Existing rows are cleared rather than backfilled.** A proposal is not a fact -- one slot per
week, replaced in place by every solve, discarded on approval -- so what a delete costs is a
proposal awaiting assent, which the next solve of that week produces again. A backfilled version
would be this column's one job stated wrongly, and a nullable column would push the same
guess onto every reader.

Every literal below is spelled here rather than imported. A revision describes the schema at its own
point in the chain and is replayed forever against databases at that point, so a value read from the
workspace's live code would describe the schema as it is now instead.

Revision ID: 0042_pending_weights
Revises: 0041_pins
Create Date: 2026-08-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0042_pending_weights"
down_revision: str | None = "0041_pins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "pending_proposals"
WEIGHT_SET_VERSION = "weight_set_version"

# Spelled out rather than composed, so the statement is a constant this file can be read against.
CLEAR_THE_SLOTS = "DELETE FROM pending_proposals"


def upgrade() -> None:
    op.execute(sa.text(CLEAR_THE_SLOTS))
    op.add_column(TABLE, sa.Column(WEIGHT_SET_VERSION, sa.Integer(), nullable=False))


def downgrade() -> None:
    op.drop_column(TABLE, WEIGHT_SET_VERSION)
