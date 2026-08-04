"""routines

The circadian frame: the spans that bound a day and make discretionary time computable.

**There is no ``area_id`` column, and the absence is the design.** A routine defines how much
time exists, so it is not competing for it: it carries no Area, it therefore carries no pigment,
and it never appears in Area budget arithmetic. A column here would let the frame be charged to a
wedge of the pie whose denominator had already subtracted it.

``target_time`` is wall time: no date and no zone. It becomes an instant per day, resolved
against the zone active on that day, which is what makes ``Wake 05:00`` mean 05:00 wherever the
user is. Storing an instant would freeze the frame to the zone it was authored in.

``min_duration_minutes`` is the elastic floor, and the sleep floor is this column on the sleep
routine. There is nowhere else it lives. The check constraint permits a value below the target,
which is what makes a routine elastic; the boundary defaults it to equality, so a routine is
inelastic unless the caller asks for give. There is no sleep-specific column and no
sleep-specific rule: sleep is simply the routine users give a range to.

``flex_band_minutes`` is how far a placement may SHIFT the routine. Nothing resizes one, so there
is deliberately no column for a resized duration: an occurrence's effective duration is derived
per week rather than stored.

No unique constraint on the title. Two routines may share one legitimately, a morning and an
evening ``Shower`` being the obvious pair, and nothing about a routine's identity rests on its
title.

Every bound and every name below is spelled here rather than imported. A revision describes the
schema at its own point in the chain and is replayed forever against databases at that point, so
a value read from the workspace's live code would describe the schema as it is now instead.

Revision ID: 0015_routines
Revises: 0013_tasks
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0015_routines"
# The head recorded when this work branched was `0007_calendar_sources`. This wave adds six
# migrations over disjoint tables, and a chain has exactly one head, so each is chained onto
# whichever of them landed before it rather than onto that branch point.
down_revision: str | None = "0013_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "routines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        # Wall time, no zone. Resolved against whichever zone is active on the day it
        # materializes on.
        sa.Column("target_time", sa.Time(), nullable=False),
        # The TARGET span, in minutes. A routine is a span, not a marker.
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        # The elastic floor, and the sleep floor on the sleep routine. Equal to the target unless
        # the caller asked for give.
        sa.Column("min_duration_minutes", sa.SmallInteger(), nullable=False),
        # How far a placement may SHIFT the routine, never how far it may shrink it.
        sa.Column("flex_band_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        # Without a duration there is nothing to subtract from the day. The upper bound is a day,
        # because a routine materializes once per local date and a longer span would overlap its
        # own next occurrence.
        sa.CheckConstraint(
            "duration_minutes BETWEEN 1 AND 1440", name=op.f("ck_routines_duration_is_a_span")
        ),
        # A floor below the target is what makes a routine elastic. A floor at zero would let the
        # frame be compressed away rather than negotiated with.
        sa.CheckConstraint(
            "min_duration_minutes > 0 AND min_duration_minutes <= duration_minutes",
            name=op.f("ck_routines_minimum_is_within_the_target"),
        ),
        sa.CheckConstraint(
            "flex_band_minutes BETWEEN 0 AND 720",
            name=op.f("ck_routines_flex_band_shifts_within_half_a_day"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_routines_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routines")),
    )
    # Every read is this tenant's whole frame, in the order the day runs.
    op.create_index(
        "ix_routines_tenant_id_target_time", "routines", ["tenant_id", "target_time"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_routines_tenant_id_target_time", table_name="routines")
    op.drop_table("routines")
