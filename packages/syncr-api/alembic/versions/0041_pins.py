"""pins: the block a pin names, and the one pin per binding per week that follows from it

Two changes to ``pins``, and both come from the same fact: a pin is the user's answer to "where
does this content go THIS week", and a person has one answer at a time.

**A block id is denormalized onto the row.** A block id is a digest of the week and the content
identity, and the pin route is handed one: the client drags a rendered block, and the only handle it
has is that block's id. Storing it is what lets the release path find the row by the identifier the
request carries, and it is the same denormalization ``block_outcomes.block_id`` and
``conflicts.block_id`` already hold, for the same reason -- a fact about a week that happened
outlives the block it names.

**A unique index makes one pin per binding per week structural.** Dragging the same block twice
states one preference twice, and two rows would constrain one solve to two intervals: the solver
seeds a pinned binding from the pin naming it, so a second row would make which interval wins an
accident of read order. The write path upserts, and this index is what makes that an invariant
rather than a rule the repository remembers.

**Half the counterfactual becomes ``NOT NULL``, which is the half a writer can know at insert.**
``PN3`` and ``B1`` say every pin persists the placement it superseded and what replacing it cost,
permanently, because the reason panel renders both from the pin rather than by walking the edit log.
The superseded placement is where the plan of record holds the block, so a route that has to find
that block in a stored document always knows it: nullable made that a rule a writer remembers, and
this makes it a shape.

**The price stays nullable, and the reason is an ordering the arithmetic forces.** What the user's
choice cost is a difference of two objective evaluations over one week's resolved inputs, and those
inputs are what the pin changes: the assembly has to see the pin to answer the verdict the response
carries. So the row exists before its price does, both writes are in one transaction, and no reader
ever sees a pin without its cost. A ``CHECK`` cannot express that, because Postgres has no
deferrable one; what holds it instead is that pricing is the only other statement against this
table, and a test asserts every committed pin carries a delta.

The check constraint over the superseded pair is restated with the nullability. Paired nullability
is what it could say while either column could be absent, and with neither absent that reading is
trivially true. What is left to hold is that the span is half-open, the shape the pin's own interval
carries.

What the upsert costs is the earlier ROW, not the earlier record: every pin writes an
``edit_events`` row in the same transaction, that table is append-only and never pruned, and it
carries the same pair, the same objective delta and the same weight-set version. So the training
label survives a re-pin and a release, and the pin row is what stops being a constraint.

The week is not in the index. A block id is a digest of the week and the binding, so per-week
uniqueness follows from the columns that are there, and a redundant column would invite the reader
to look for a reason it is needed.

Existing rows are not migrated and none exists: nothing in any deployment wrote this table before
this revision, which is why ``block_id`` can be ``NOT NULL`` without a backfill. The constraint
would fail loudly rather than silently if a row did exist, which is the correct direction for a
fact table.

Every literal below is spelled here rather than imported. A revision describes the schema at its own
point in the chain and is replayed forever against databases at that point, so a value read from the
workspace's live code would describe the schema as it is now instead.

Revision ID: 0041_pins
Revises: 0039_conflicts
Create Date: 2026-08-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0041_pins"
down_revision: str | None = "0039_conflicts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "pins"
BLOCK_ID = "block_id"

# The same width every other block-id column in this schema holds: a SHA-256 digest as hex.
BLOCK_ID_LENGTH = 64

ONE_PIN_PER_BLOCK_INDEX = "uq_pins_tenant_id_block_id"

# The half of the counterfactual a writer knows at insert: where the plan of record held the block.
# The price is not here, because it is derived from an assembly the pin itself changes.
SUPERSEDED_PLACEMENT = ("superseded_starts_at", "superseded_ends_at")

# The constraint over that pair, whose reading changes with the nullability above.
SUPERSEDED_IS_WHOLE = "superseded_placement_is_whole"
PAIRED_NULLABILITY = "(superseded_starts_at IS NULL) = (superseded_ends_at IS NULL)"
HALF_OPEN = "superseded_starts_at < superseded_ends_at"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(BLOCK_ID, sa.String(BLOCK_ID_LENGTH), nullable=False))
    op.create_index(ONE_PIN_PER_BLOCK_INDEX, TABLE, ["tenant_id", BLOCK_ID], unique=True)
    for column in SUPERSEDED_PLACEMENT:
        op.alter_column(TABLE, column, nullable=False)
    op.drop_constraint(SUPERSEDED_IS_WHOLE, TABLE, type_="check")
    op.create_check_constraint(SUPERSEDED_IS_WHOLE, TABLE, sa.text(HALF_OPEN))


def downgrade() -> None:
    op.drop_constraint(SUPERSEDED_IS_WHOLE, TABLE, type_="check")
    op.create_check_constraint(SUPERSEDED_IS_WHOLE, TABLE, sa.text(PAIRED_NULLABILITY))
    for column in SUPERSEDED_PLACEMENT:
        op.alter_column(TABLE, column, nullable=True)
    op.drop_index(ONE_PIN_PER_BLOCK_INDEX, table_name=TABLE)
    op.drop_column(TABLE, BLOCK_ID)
