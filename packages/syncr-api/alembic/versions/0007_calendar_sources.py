"""calendar sources and their embedded sync state

One table. Many sources are read as anchors and exactly one is written to as the projection,
and the difference between those two roles is what most of the constraints here are about.

The PARTIAL UNIQUE index is the one-write-target invariant. At most one source per tenant may
hold ``role = 'write-target'``, and the database is what says so: two calendars each believing
they are the projection would both be reconciled destructively, and the plan would appear
twice on the user's phone.

The horizon biconditional makes "a horizon belongs to the write target" structural rather than
a rule a repository keeps. A write target always carries a bound past which it will not delete,
and an anchor source never carries one, so no reader has to decide what a projection horizon on
a read-only feed would mean.

The unique constraint on ``(tenant_id, provider, external_id)`` stops the same feed being added
twice, which would double every anchor it contributes and make the solver treat one lecture as
two overlapping commitments.

Sync state is embedded rather than kept in a table of its own: there is exactly one per source,
every read of a source wants it, and a join for a last-sync time would be a join on every panel
render. ``rejections`` is a JSONB array for the same reason, replaced wholesale per attempt,
with nothing querying across it.

Every value this revision names is spelled out here rather than imported. A revision describes
the schema at its own point in the chain and is replayed against databases at that point, so an
INSERT or a CHECK built from a live constant names whatever that constant holds today.

The chain: ``down_revision`` was ``0005_oauth_authorization_server``, the head recorded when
this work branched. The areas revision landed in the shared tree first, so this is chained onto
it rather than leaving the chain with two heads, which ``alembic upgrade head`` refuses. The two
tables are disjoint, so the order between them decides nothing.

Revision ID: 0007_calendar_sources
Revises: 0006_areas_and_projects
Create Date: 2026-08-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0007_calendar_sources"
down_revision: str | None = "0006_areas_and_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "calendar_sources"
WRITE_TARGET_PREDICATE = "role = 'write-target'"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=6), nullable=False),
        sa.Column("role", sa.String(length=13), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        # A normalized feed URL for an ICS source, a calendarId for a Google one.
        sa.Column("external_id", sa.String(length=2048), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        # Write-target only, per the biconditional below. Defaults to 14 when the role is
        # assigned; the default lives in the application, because the column is null for
        # every anchor source and a column default cannot express that.
        sa.Column("horizon_days", sa.SmallInteger(), nullable=True),
        # The embedded sync state, written on every attempt so staleness is computable.
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("events_read", sa.Integer(), nullable=False),
        sa.Column("anchors_current", sa.Integer(), nullable=False),
        # `none_as_null` so an attempt that rejected nothing stores SQL NULL rather than the
        # JSON value `null`, which a query looking for one would find.
        sa.Column("rejections", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "provider IN ('google', 'ics')", name=op.f(f"ck_{TABLE}_provider_is_known")
        ),
        sa.CheckConstraint(
            "role IN ('anchor-source', 'write-target')", name=op.f(f"ck_{TABLE}_role_is_known")
        ),
        sa.CheckConstraint(
            f"({WRITE_TARGET_PREDICATE}) = (horizon_days IS NOT NULL)",
            name=op.f(f"ck_{TABLE}_only_the_write_target_carries_a_horizon"),
        ),
        sa.CheckConstraint(
            "horizon_days IS NULL OR horizon_days BETWEEN 1 AND 90",
            name=op.f(f"ck_{TABLE}_horizon_days_within_the_projection_range"),
        ),
        sa.CheckConstraint(
            "events_read >= 0 AND anchors_current >= 0",
            name=op.f(f"ck_{TABLE}_counts_are_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    # One source per feed per tenant. A unique INDEX rather than a unique CONSTRAINT, matching
    # the convention plan storage set: the metadata's `uq` naming rule derives a name from the
    # first column alone, so a constraint spanning three would be named after one of them.
    op.create_index(
        f"uq_{TABLE}_tenant_id_provider_external_id",
        TABLE,
        ["tenant_id", "provider", "external_id"],
        unique=True,
    )
    op.create_index(
        f"uq_{TABLE}_tenant_id_write_target",
        TABLE,
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text(WRITE_TARGET_PREDICATE),
    )
    op.create_index(f"ix_{TABLE}_tenant_id_created_at", TABLE, ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_tenant_id_created_at", table_name=TABLE)
    op.drop_index(f"uq_{TABLE}_tenant_id_write_target", table_name=TABLE)
    op.drop_index(f"uq_{TABLE}_tenant_id_provider_external_id", table_name=TABLE)
    op.drop_table(TABLE)
