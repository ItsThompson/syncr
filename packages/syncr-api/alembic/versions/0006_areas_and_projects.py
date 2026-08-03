"""areas and projects

Two tables, one concern: the wedges of the allocation model, and the time-boxed pushes
inside them.

``areas`` is self-referencing and the reference is nullable, which is what makes a top-level
Area and a child Area one table rather than two. It cascades on delete because deleting a
TENANT deletes every one of its Areas in one statement, and a restricting constraint would
refuse that while a child still pointed at its parent. Nothing else deletes an Area: they are
permanent, not completed and not archived, and no route removes one.

The unique index on ``(tenant_id, name)`` is load-bearing rather than tidy. The pigment ramp
holds twelve steps and repeats past twelve Areas, at which point identity rests on the hatch
and the Area's name, so two Areas holding one name would leave a wedge with nothing to
identify it.

``projects`` carries no budget column at all, and that absence is the design. A Project
inherits its parent Area's allocation, so a time-boxed push needs no wedge of its own, and
completing one leaves its historical time attribution intact because the attribution was
always to the Area.

``default_preference_id`` carries no foreign key. Preferences are created by a later revision
and the column has to exist from the one that creates ``areas``, because the Area is where a
preference's owner is declared.

Every bound and every vocabulary member below is spelled here rather than imported. A revision
describes the schema at its own point in the chain and is replayed forever against databases at
that point, so a value read from the workspace's live code would describe the schema as it is
now instead.

Revision ID: 0006_areas_and_projects
Revises: 0005_oauth_authorization_server
Create Date: 2026-08-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0006_areas_and_projects"
down_revision: str | None = "0005_oauth_authorization_server"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "areas",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Null for a top-level Area. A child's time rolls up into its parent in reports.
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        # An index into the sealed twelve-step ramp, assigned from the deal. Never a colour:
        # there is no colour picker anywhere in the product.
        sa.Column("pigment_index", sa.SmallInteger(), nullable=False),
        # The share of discretionary time REMAINING after every floor is honored. Null means
        # the Area declares no share, which is not the same as declaring zero. Shares summing
        # past 100 across Areas are accepted and reported as oversubscription.
        sa.Column("budget_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        # The absolute weekly minimum, in hours as the user authors it. A hard solver
        # constraint. Bounded at 168 to reject a floor no week could meet, which is not a
        # claim that a week is 168 hours: a transition week is 167 or 169.
        sa.Column("floor_hours", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("default_preference_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "budget_percent IS NULL OR budget_percent BETWEEN 0 AND 100",
            name=op.f("ck_areas_budget_percent_is_a_share"),
        ),
        sa.CheckConstraint(
            "floor_hours IS NULL OR floor_hours BETWEEN 0 AND 168",
            name=op.f("ck_areas_floor_hours_could_be_met"),
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_areas_parent_is_another_area")
        ),
        sa.CheckConstraint(
            "pigment_index BETWEEN 0 AND 11", name=op.f("ck_areas_pigment_index_is_on_the_ramp")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["areas.id"],
            name=op.f("fk_areas_parent_id_areas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_areas_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_areas")),
    )
    # Identity past twelve Areas rests on the hatch and the name, so the name has to be unique
    # for that to be true.
    op.create_index("uq_areas_tenant_id_name", "areas", ["tenant_id", "name"], unique=True)
    # Every list read is this tenant's Areas in the order they were declared, which is also the
    # order the ramp dealt their pigments.
    op.create_index(
        "ix_areas_tenant_id_created_at", "areas", ["tenant_id", "created_at"], unique=False
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Not nullable and not a list: a Project never spans Areas, which is what keeps an hour
        # spent on it attributable to exactly one Area.
        sa.Column("area_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        # A varchar plus a CHECK rather than a Postgres enum type, so adding a status later is
        # a constraint edit rather than an ALTER TYPE. `create_constraint` is stated because
        # SQLAlchemy defaults it to False, which would leave the column accepting any string of
        # the right length.
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "completed",
                "abandoned",
                name="project_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["area_id"], ["areas.id"], name=op.f("fk_projects_area_id_areas"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_projects_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    # Every read is either this tenant's projects or the ones inside one Area.
    op.create_index(
        "ix_projects_tenant_id_area_id", "projects", ["tenant_id", "area_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_projects_tenant_id_area_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_areas_tenant_id_created_at", table_name="areas")
    op.drop_index("uq_areas_tenant_id_name", table_name="areas")
    op.drop_table("areas")
