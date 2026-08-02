"""settings and travel overrides

Two tables, one concern: where the user is, and how they read a day.

``settings`` takes ``tenant_id`` as its PRIMARY KEY, so "one row per tenant" is a property
of the database rather than a rule a repository keeps. The row is written on the first
change, not at sign-up: a tenant with no row reads the declared defaults, so a read never
has to write.

Neither table carries an ``updated_at``. Nothing reads one, and what a settings change
means to the rest of the product is recorded where the product looks for it: the week
input version of every week the change affects.

The non-overlap rule on ``travel_overrides`` is deliberately NOT a constraint here. An
exclusion constraint over a date range would be a second implementation of a rule
``syncr_domain.zones.ZoneProfile`` already owns, and two implementations of one rule can
disagree. The service serializes declarations on the tenant's own ``settings`` row, so the
domain check runs against a state nobody else can change underneath it. ``start_date <=
end_date`` IS a constraint, because that one is about the row rather than about the set.

Revision ID: 0003_settings_and_overrides
Revises: 0002_tenancy_users_sessions
Create Date: 2026-08-02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0003_settings_and_overrides"
down_revision: str | None = "0002_tenancy_users_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("visible_hours", sa.SmallInteger(), nullable=False),
        # Wall time, no zone: it resolves against the zone active on the day rendered.
        sa.Column("day_start", sa.Time(), nullable=False),
        sa.Column("day_end", sa.Time(), nullable=False),
        # A varchar plus a CHECK rather than a Postgres enum type, so adding a cadence
        # later is a constraint edit rather than an ALTER TYPE. `create_constraint` is
        # stated because SQLAlchemy defaults it to False, which would leave the column
        # accepting any string of the right length.
        sa.Column(
            "review_cadence",
            sa.Enum(
                "on_demand",
                "quarterly",
                name="review_cadence",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("home_zone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "day_start < day_end", name=op.f("ck_settings_day_start_before_day_end")
        ),
        sa.CheckConstraint(
            "visible_hours BETWEEN 6 AND 24",
            name=op.f("ck_settings_visible_hours_within_the_zoom_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_settings_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_settings")),
    )
    op.create_table(
        "travel_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Both dates inclusive.
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("zone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "start_date <= end_date",
            name=op.f("ck_travel_overrides_start_date_not_after_end_date"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_travel_overrides_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_travel_overrides")),
    )
    # Every read is this tenant's overrides in date order, which is also the order
    # `ZoneProfile` sorts them into.
    op.create_index(
        "ix_travel_overrides_tenant_id_start_date",
        "travel_overrides",
        ["tenant_id", "start_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_travel_overrides_tenant_id_start_date", table_name="travel_overrides")
    op.drop_table("travel_overrides")
    op.drop_table("settings")
