"""off-plan periods

One table: the spans a tenant declared off, stored as a pair of instants and nothing else.

Four properties of it are the design rather than incidental.

**The interval is half-open, ``[start, end)``.** ``start`` is inside the period and ``end`` is
not, so a period ending at a Monday's local midnight ends exactly where the following week
begins and reaches nothing inside it. That reading is Postgres's own for a ``tstzrange`` built
with default bounds, and it is the reading every consumer of these two columns uses.

**``end`` is a reserved word in SQL and the column is named ``end`` anyway.** The domain calls
the far bound ``end``, and a column named for something else would make every hand-written query
translate. SQLAlchemy quotes an identifier the dialect reserves; anything written by hand against
this table has to quote ``"end"`` too, including the CHECK below.

**There is no week column and no duration column.** A period spanning two ISO weeks is ONE row.
Which weeks it touches is a function of its two instants and the tenant's zone, so a stored week
would be a second answer to that question and would be wrong the moment the home zone changed.

**Non-overlap is not a constraint here.** Enforcing it in SQL would need an exclusion constraint
over a range type, which is a second implementation of a rule the domain already owns, and the
two could then disagree. The service serializes every declaration on the tenant's own settings
row instead. ``travel_overrides`` states the same reasoning for the same invariant.

The quarter-hour grid is not a constraint either. A row off the grid renders a few minutes off
the grid lines, which is a degradation rather than a fault, so the rule is stated once in the
domain rather than copied into SQL where it would have to be edited in step.

Every value this revision names is spelled out here rather than imported. A revision describes
the schema at its own point in the chain and is replayed against databases at that point, so a
CHECK or a length built from a live constant names whatever that constant holds today.

The chain: this work branched when ``0007_calendar_sources`` was head, and five sibling tickets
add a revision over disjoint tables in the same wave. Sibling revisions landed in the shared tree
first, so this is chained onto the head they left rather than onto 0007, which would leave the
chain with two heads and ``alembic upgrade head`` refusing. The tables are disjoint, so the order
between them decides nothing.

Revision ID: 0017_off_plan_periods
Revises: 0019_anchors
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially, because five sibling tickets add a revision in
# the same wave and a sequential number would collide between them.
revision: str = "0017_off_plan_periods"
down_revision: str | None = "0019_anchors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "off_plan_periods"

# A label is rendered in the gutter beside a hatched band, which is a narrow space.
LABEL_MAX_LENGTH = 60


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        # The half-open bounds. Instants, not wall times: a span crossing a daylight-saving
        # transition is 68 elapsed hours where its two wall times differ by 67, and every
        # downstream figure needs the elapsed one.
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        # False means no routine materializes inside the span; true means routines materialize
        # and nothing else does. Defaulted in the database as well as in the application, so a
        # row inserted by hand carries the reading the product documents.
        sa.Column("keep_frame", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("label", sa.String(length=LABEL_MAX_LENGTH), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        # A reversed row is unreadable rather than merely odd: every reader builds an interval
        # from the pair, and an interval needs a positive length.
        sa.CheckConstraint('start < "end"', name=op.f(f"ck_{TABLE}_start_before_end")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    # Every read is either this tenant's periods in time order or the ones overlapping one week's
    # span, and both lead with the tenant and then with the start.
    op.create_index(f"ix_{TABLE}_tenant_id_start", TABLE, ["tenant_id", "start"])


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_tenant_id_start", table_name=TABLE)
    op.drop_table(TABLE)
