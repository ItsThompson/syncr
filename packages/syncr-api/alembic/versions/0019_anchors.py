"""anchors and anchor types

Two tables. One holds facts imported from a calendar; the other holds the declaration of what
every commitment of a class reserves around itself.

The UNIQUE index on ``(tenant_id, source_id, external_uid)`` is the reconciliation key, and the
database is what says so. Diffing on a title and a time would read a lecture moved by an hour as
one commitment cancelled and another created, and every block the first displaced would be freed
and then displaced again. The source is part of the key because two calendars can each publish the
same meeting: they are two anchors, so excluding one does not remove the other's occupancy.

The source cascades, which is what makes removing a feed remove the occupancy it contributed in
one statement. ``anchor_type_id`` is ``SET NULL``, so a removed type leaves its commitments as
opaque busy time rather than removing them.

Three check constraints on ``anchor_types`` are the boundary rules this revision exists to state.

The transit rule refuses a lead shorter than the journey, because the outbound leg would still be
travelling when the commitment started.

The prep rule refuses a prep lead shorter than the prep plus the transit lead, because prep would
still be running when the outbound leg left. **It is guarded on a non-zero prep duration and that
guard is load-bearing.** With no prep there is nothing to collide with, and without the guard the
constraint rejects a type with transit and no prep, which is a real declared class of commitment.

The scope rule makes the three-way recovery choice explicit: the forbidden-Area list is non-empty
for exactly the ``areas`` scope. An empty list once meant "forbids everything", which reads as an
oversight rather than as a decision, and it silently stopped being correct the moment a new Area
was declared.

``match_source_id`` carries NO foreign key, and that is a decision rather than an omission. Both
foreign-key behaviors are wrong: ``CASCADE`` would delete a hand-authored shadow declaration
because the user removed a feed, and ``SET NULL`` would silently widen the rule from "commitments
from this calendar" to "commitments from every calendar". With no constraint the identifier simply
stops matching anything, because every anchor of a removed source is removed with it. The
application confirms the source exists when the rule is written.

``forbidden_area_ids`` carries no foreign key either, as a consequence of being JSONB. That is
safe because an Area is permanent in P0 -- not completed, not archived, and no route removes one --
so the only thing that removes an Area is removing its tenant, which removes these rows too.

Every value this revision names is spelled out here rather than imported. A revision describes the
schema at its own point in the chain and is replayed against databases at that point, so an INSERT
or a CHECK built from a live constant names whatever that constant holds today.

The chain: ``down_revision`` is the head recorded when this work branched. Tickets 13 to 18 add
revisions in the same wave over disjoint tables, so the order between them decides nothing; a
sibling landing first is rebased onto rather than edited, because ``alembic upgrade head`` refuses
two heads.

Revision ID: 0019_anchors
Revises: 0015_routines
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0019_anchors"
down_revision: str | None = "0015_routines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANCHORS = "anchors"
ANCHOR_TYPES = "anchor_types"

# The lead a null `transit_lead_minutes` stands for: abutting the commitment.
EFFECTIVE_TRANSIT_LEAD = "COALESCE(transit_lead_minutes, transit_duration_minutes)"

# A lead may reach a week, because the week assembler expands its anchor read backwards by the
# largest lead any type declares. A duration may reach a day, because a buffer longer than a day
# is a period to declare off-plan rather than a shadow.
LEAD_MINUTES_MAX = 7 * 24 * 60
DURATION_MINUTES_MAX = 24 * 60
FORBIDDEN_AREAS_MAX = 100


def _minutes(column: str, ceiling: int, *, nullable: bool = False) -> sa.CheckConstraint:
    bounded = f"{column} BETWEEN 0 AND {ceiling}"
    predicate = f"{column} IS NULL OR {bounded}" if nullable else bounded
    return sa.CheckConstraint(
        predicate, name=op.f(f"ck_{ANCHOR_TYPES}_{column}_is_a_plausible_number_of_minutes")
    )


def upgrade() -> None:
    op.create_table(
        ANCHOR_TYPES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        # Rules evaluate in this order and the FIRST match wins. Not unique: a reorder rewrites
        # positions row by row, and a unique constraint would reject the intermediate states of
        # any permutation that is not a rotation.
        sa.Column("rule_order", sa.SmallInteger(), nullable=False),
        sa.Column("match_title_contains", sa.String(length=200), nullable=True),
        # No foreign key, per the module docstring.
        sa.Column("match_source_id", sa.Uuid(), nullable=True),
        sa.Column("prep_lead_minutes", sa.Integer(), nullable=False),
        sa.Column("prep_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("prep_area_id", sa.Uuid(), nullable=True),
        # Null is not zero: null means the outbound leg abuts the commitment, and zero would mean
        # a leg that starts at it and is therefore not a journey to it.
        sa.Column("transit_lead_minutes", sa.Integer(), nullable=True),
        sa.Column("transit_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("return_transit_minutes", sa.Integer(), nullable=False),
        sa.Column("transit_area_id", sa.Uuid(), nullable=True),
        sa.Column("post_buffer_minutes", sa.Integer(), nullable=False),
        sa.Column("post_scope", sa.String(length=5), nullable=False),
        sa.Column("forbidden_area_ids", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "post_scope IN ('none', 'all', 'areas')",
            name=op.f(f"ck_{ANCHOR_TYPES}_post_scope_is_known"),
        ),
        sa.CheckConstraint(
            "rule_order >= 0", name=op.f(f"ck_{ANCHOR_TYPES}_rule_order_is_a_position")
        ),
        _minutes("prep_lead_minutes", LEAD_MINUTES_MAX),
        _minutes("prep_duration_minutes", DURATION_MINUTES_MAX),
        _minutes("transit_lead_minutes", LEAD_MINUTES_MAX, nullable=True),
        _minutes("transit_duration_minutes", DURATION_MINUTES_MAX),
        _minutes("return_transit_minutes", DURATION_MINUTES_MAX),
        _minutes("post_buffer_minutes", DURATION_MINUTES_MAX),
        sa.CheckConstraint(
            "transit_lead_minutes IS NULL OR transit_lead_minutes >= transit_duration_minutes",
            name=op.f(f"ck_{ANCHOR_TYPES}_the_outbound_leg_arrives_before_the_anchor"),
        ),
        sa.CheckConstraint(
            "prep_duration_minutes = 0 OR "
            f"prep_lead_minutes >= prep_duration_minutes + {EFFECTIVE_TRANSIT_LEAD}",
            name=op.f(f"ck_{ANCHOR_TYPES}_prep_finishes_before_the_outbound_leg_leaves"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(forbidden_area_ids) = 'array' AND "
            "(post_scope = 'areas') = (jsonb_array_length(forbidden_area_ids) > 0)",
            name=op.f(f"ck_{ANCHOR_TYPES}_only_the_areas_scope_names_areas"),
        ),
        sa.CheckConstraint(
            f"jsonb_array_length(forbidden_area_ids) <= {FORBIDDEN_AREAS_MAX}",
            name=op.f(f"ck_{ANCHOR_TYPES}_the_forbidden_areas_are_a_bounded_list"),
        ),
        sa.ForeignKeyConstraint(
            ["prep_area_id"],
            ["areas.id"],
            name=op.f(f"fk_{ANCHOR_TYPES}_prep_area_id_areas"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transit_area_id"],
            ["areas.id"],
            name=op.f(f"fk_{ANCHOR_TYPES}_transit_area_id_areas"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{ANCHOR_TYPES}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ANCHOR_TYPES}")),
    )
    # A matched type is shown ON the commitment, so two types holding one name would leave a
    # reader unable to tell which rule fired. A unique INDEX rather than a unique CONSTRAINT,
    # matching the convention plan storage set.
    op.create_index(
        f"uq_{ANCHOR_TYPES}_tenant_id_name", ANCHOR_TYPES, ["tenant_id", "name"], unique=True
    )
    op.create_index(
        f"ix_{ANCHOR_TYPES}_tenant_id_rule_order", ANCHOR_TYPES, ["tenant_id", "rule_order"]
    )

    op.create_table(
        ANCHORS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_uid", sa.String(length=512), nullable=False),
        sa.Column("series_uid", sa.String(length=512), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        # Absolute instants, and deliberately NOT snapped to the quarter hour: an imported
        # commitment is a fact and keeps its real time, even at :07.
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        # Stored with NO reader. Transit is declared per anchor type rather than derived from a
        # location, which reinterprets PRD 3.4's "generated from a location": routing needs a maps
        # integration, a home address, and a travel-mode preference, none of which is in this
        # epic. The column exists so the fact is not discarded and a later epic needs no backfill.
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("anchor_type_id", sa.Uuid(), nullable=True),
        sa.Column("type_overridden", sa.Boolean(), nullable=False),
        sa.Column("possibly_stale", sa.Boolean(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "ends_at > starts_at", name=op.f(f"ck_{ANCHORS}_an_anchor_occupies_time")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["calendar_sources.id"],
            name=op.f(f"fk_{ANCHORS}_source_id_calendar_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["anchor_type_id"],
            [f"{ANCHOR_TYPES}.id"],
            name=op.f(f"fk_{ANCHORS}_anchor_type_id_{ANCHOR_TYPES}"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{ANCHORS}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ANCHORS}")),
    )
    # THE RECONCILIATION KEY.
    op.create_index(
        f"uq_{ANCHORS}_tenant_id_source_id_external_uid",
        ANCHORS,
        ["tenant_id", "source_id", "external_uid"],
        unique=True,
    )
    # The span read the week view and the assembler both make.
    op.create_index(f"ix_{ANCHORS}_tenant_id_starts_at", ANCHORS, ["tenant_id", "starts_at"])
    # Retyping persists on the SERIES, so every occurrence of one is written together.
    op.create_index(f"ix_{ANCHORS}_tenant_id_series_uid", ANCHORS, ["tenant_id", "series_uid"])
    # Removing or re-evaluating a type reaches every commitment holding it.
    op.create_index(
        f"ix_{ANCHORS}_tenant_id_anchor_type_id", ANCHORS, ["tenant_id", "anchor_type_id"]
    )


def downgrade() -> None:
    op.drop_index(f"ix_{ANCHORS}_tenant_id_anchor_type_id", table_name=ANCHORS)
    op.drop_index(f"ix_{ANCHORS}_tenant_id_series_uid", table_name=ANCHORS)
    op.drop_index(f"ix_{ANCHORS}_tenant_id_starts_at", table_name=ANCHORS)
    op.drop_index(f"uq_{ANCHORS}_tenant_id_source_id_external_uid", table_name=ANCHORS)
    op.drop_table(ANCHORS)
    op.drop_index(f"ix_{ANCHOR_TYPES}_tenant_id_rule_order", table_name=ANCHOR_TYPES)
    op.drop_index(f"uq_{ANCHOR_TYPES}_tenant_id_name", table_name=ANCHOR_TYPES)
    op.drop_table(ANCHOR_TYPES)
