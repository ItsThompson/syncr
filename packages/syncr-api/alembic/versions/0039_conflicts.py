"""conflicts: the identity a raise is idempotent over, and the binding that outlives the block

Two changes to ``conflicts``, both about the fact that a conflict is retained forever and asked
about once.

**A binding is denormalized onto the row.** The table already carries ``block_id``, which is a
digest of the week and the content identity, and a digest cannot be compared across weeks: the same
``Leetcode`` task collided with in four consecutive weeks holds four unrelated ids. The weekly
session's repeated-collision item is stated over "the same anchor and the same binding in three or
more weeks", so without the binding the retention this table exists for computes nothing. It is the
same denormalization ``block_outcomes.binding`` carries and for the same reason: a fact about a week
that happened outlives the block it names.

**A partial unique index makes one question per commitment and block structural.** Detection runs
at ingest on every sync that changed an anchor, and again on the commit path of every solve, so the
same overlap is presented many times. Two states must not raise again:

| The row holds | Why it is not asked again |
|---|---|
| ``resolved_at IS NULL`` | the question is already open and waiting for an answer |
| ``resolution = 'kept-both'`` | the user accepted the overlap, and it is not re-raised |

A resolution of ``moved`` or ``retyped`` is deliberately outside the predicate. Each asks for a
change -- the block relocates, or the commitment's type changes what it casts -- so the same
collision appearing afterwards is a new event rather than the same question, and the user has to
see that the change did not settle it.

The week is not in the index. A block id is a digest of the week and the binding, so per-week
uniqueness follows from the columns that are there, and a redundant column would invite the reader
to look for a reason it is needed.

Existing rows are not migrated and none exists: nothing in any deployment writes this table before
this revision. The ``NOT NULL`` would fail loudly rather than silently if one did, which is the
correct direction for a fact table.

Every literal below is spelled here rather than imported. A revision describes the schema at its own
point in the chain and is replayed forever against databases at that point, so a value read from the
workspace's live code would describe the schema as it is now instead.

Revision ID: 0039_conflicts
Revises: 0032_outcomes
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0039_conflicts"
down_revision: str | None = "0032_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "conflicts"
BINDING = "binding"

UNANSWERED_INDEX = "uq_conflicts_tenant_id_anchor_id_block_id"

# The two states that must not be raised again, spelled as the index's own predicate.
UNANSWERED = "resolved_at IS NULL OR resolution = 'kept-both'"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(BINDING, postgresql.JSONB(), nullable=False))
    op.create_index(
        UNANSWERED_INDEX,
        TABLE,
        ["tenant_id", "anchor_id", "block_id"],
        unique=True,
        postgresql_where=sa.text(UNANSWERED),
    )


def downgrade() -> None:
    op.drop_index(UNANSWERED_INDEX, table_name=TABLE)
    op.drop_column(TABLE, BINDING)
