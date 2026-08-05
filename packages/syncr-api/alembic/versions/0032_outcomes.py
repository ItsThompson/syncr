"""outcomes: one row per block, and the index the habit projection reads

Two changes to ``block_outcomes``, both about how a row is found rather than what it holds. No
column is added, because the reality-state columns arrived with ``0004_plan_storage`` and the
outcome routes write exactly them.

**The identity narrows from ``(tenant_id, block_id, revision_id)`` to ``(tenant_id, block_id)``.**
A block id is a digest of the week and the binding, so one content instance in one week keeps one
id however many revisions place it. The wider index permitted a row per plan of record, and every
consumer of this table is a count over the rows it is handed: two rows under one habit occurrence
move a rotation cursor one variant past the muscle group the user trained, and one skip stored
twice is owed twice. A count cannot tell a duplicate from a second occurrence, so the invariant is
held here instead of by each reader choosing a revision to prefer.

Existing rows are not migrated. Nothing in any deployment writes this table before this revision,
so there is no row to collapse; the unique index would fail loudly rather than silently if one
existed, which is the correct direction for a fact table.

**An expression index serves the projection that finds a habit's outcomes.** The rotation cursor
and outstanding debt are derived from every row whose binding names one of a set of habits, and
neither existing index offers that: one leads with ``occurred_at`` and the other with ``block_id``.
Measured on 60,000 rows in one tenant, at Postgres 16:

| Index | Plan | Time |
|---|---|---|
| neither | sequential scan, 59,760 rows discarded | 26.1 ms |
| this one | index scan, tenant and both keys in the condition | 1.2 ms |
| GIN ``jsonb_path_ops`` | bitmap scan, tenant as a heap FILTER | 0.7 ms |

The GIN alternative is marginally faster and was not chosen: it cannot carry ``tenant_id``, so the
scope becomes a filter applied after another tenant's rows have been read, and it costs 624 kB
against 464 kB for the same row count. A scope that is part of an index condition rather than a
post-filter is worth 0.5 ms on a read that runs once per habit collection.

Both expressions are spelled as text extractions rather than as a containment operator, because
the query is an equality over two keys and a B-tree can hold the tenant, the kind, and the entity
in one ordered condition.

Every literal below is spelled here rather than imported. A revision describes the schema at its
own point in the chain and is replayed forever against databases at that point, so a value read
from the workspace's live code would describe the schema as it is now instead.

Revision ID: 0032_outcomes
Revises: 0021_preferences
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0032_outcomes"
down_revision: str | None = "0021_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "block_outcomes"

PER_REVISION_INDEX = "uq_block_outcomes_tenant_id_block_id_revision_id"
PER_BLOCK_INDEX = "uq_block_outcomes_tenant_id_block_id"
BINDING_INDEX = "ix_block_outcomes_tenant_id_binding_entity"

# The two keys the projection matches on. Rendered through `sa.text` rather than passed as names: a
# plain string reaches `CREATE INDEX` quoted as an identifier, and Postgres then reports that no
# column called `(binding ->> 'kind')` exists.
BINDING_KIND = sa.text("(binding ->> 'kind')")
BINDING_ENTITY = sa.text("(binding ->> 'entity_id')")


def upgrade() -> None:
    op.drop_index(PER_REVISION_INDEX, table_name=TABLE)
    op.create_index(PER_BLOCK_INDEX, TABLE, ["tenant_id", "block_id"], unique=True)
    op.create_index(BINDING_INDEX, TABLE, ["tenant_id", BINDING_KIND, BINDING_ENTITY])


def downgrade() -> None:
    op.drop_index(BINDING_INDEX, table_name=TABLE)
    op.drop_index(PER_BLOCK_INDEX, table_name=TABLE)
    op.create_index(
        PER_REVISION_INDEX, TABLE, ["tenant_id", "block_id", "revision_id"], unique=True
    )
