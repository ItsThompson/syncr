"""The two tables: the facts imported from a calendar, and the shadows a type declares.

``anchors`` holds facts. Nothing in syncr writes a title, an interval, or a location except the
reconciler, and no route reaches any of them: an anchor is read-only, and the one column a user
may change is ``anchor_type_id``. The unique index on ``(tenant_id, source_id, external_uid)``
IS the reconciliation key, so "one commitment per source per UID" is the database's statement
rather than the reconciler's habit. The source cascades, which is what makes removing a feed
remove the occupancy it contributed in one statement.

``anchor_types`` holds declarations, and three of its check constraints are the boundary rules
this ticket exists to state. Each of them is also stated in
:mod:`syncr_api.anchors.rules`, which is what produces the 422 naming the member to change; the
constraints are the guarantee, because a rule that lives only in a service is a rule a second
writer skips.

The prep-collision constraint is guarded on ``prep_duration_minutes > 0`` and the guard is
load-bearing. With no prep there is nothing for transit to collide with, and without the guard
the constraint rejects a type with transit and no prep, which is the rendered ``Lecture``.

``forbidden_area_ids`` is JSONB rather than a join table: it is replaced wholesale whenever the
type is edited, nothing queries across it, and one read of a type wants all of it. It carries
no foreign key as a consequence, which is safe here because an Area is permanent in P0 -- not
completed, not archived, and no route removes one -- so the only thing that removes an Area is
removing its tenant, which removes these rows too.

``match_source_id`` carries no foreign key either, and that one is a decision rather than a
consequence. Both foreign-key behaviors are wrong: ``CASCADE`` would delete a hand-authored
shadow declaration because the user removed a feed, and ``SET NULL`` would silently WIDEN the
rule from "anchors from this calendar" to "anchors from every calendar". With no constraint the
identifier simply stops matching anything, because every anchor of a removed source is removed
with it. The service confirms the source exists when the rule is written.

The two Area columns DO use ``SET NULL``, which is the behavior the paragraph above rejects, and the
asymmetry is worth naming. Dropping the Area off a prep or transit buffer turns a BLOCK into a
forbidden window: a different product with a different budget consequence, not a widened rule. That
is a smaller and more visible change than silently matching every calendar, and it is unreachable in
P0 because no route removes an Area. If a later epic adds one, this is the decision to revisit, and
``test_an_areas_removal_leaves_the_type_and_its_own_areas_alone`` pins exactly what it does today.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.anchors.config import (
    ANCHOR_LOCATION_MAX_LENGTH,
    ANCHOR_TITLE_MAX_LENGTH,
    ANCHOR_TYPE_NAME_MAX_LENGTH,
    ANCHOR_TYPES_TABLE,
    ANCHORS_TABLE,
    DURATION_MINUTES_MAX,
    EXTERNAL_UID_MAX_LENGTH,
    FORBIDDEN_AREAS_MAX,
    FORBIDS_AREAS,
    LEAD_MINUTES_MAX,
    MATCH_TITLE_MAX_LENGTH,
    MINUTES_MIN,
    POST_SCOPES,
)
from syncr_api.areas.config import AREAS_TABLE
from syncr_api.calendars.config import CALENDAR_SOURCES_TABLE
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped

_SCOPE_VALUES = ", ".join(f"'{scope}'" for scope in POST_SCOPES)
# The lead a null `transit_lead_minutes` stands for: abutting the anchor.
_EFFECTIVE_TRANSIT_LEAD = "COALESCE(transit_lead_minutes, transit_duration_minutes)"


def _minutes(column: str, ceiling: int, *, nullable: bool = False) -> CheckConstraint:
    """A minute column held between zero and its ceiling.

    Built rather than written eight times, so a bound cannot be applied to seven of the eight
    columns that need it.
    """
    bounded = f"{column} BETWEEN {MINUTES_MIN} AND {ceiling}"
    predicate = f"{column} IS NULL OR {bounded}" if nullable else bounded
    return CheckConstraint(predicate, name=f"{column}_is_a_plausible_number_of_minutes")


class AnchorType(Base, TenantScoped):
    """One declared class of commitment, and the shadow every anchor of it casts."""

    __tablename__ = ANCHOR_TYPES_TABLE
    __table_args__ = (
        CheckConstraint(f"post_scope IN ({_SCOPE_VALUES})", name="post_scope_is_known"),
        CheckConstraint("rule_order >= 0", name="rule_order_is_a_position"),
        _minutes("prep_lead_minutes", LEAD_MINUTES_MAX),
        _minutes("prep_duration_minutes", DURATION_MINUTES_MAX),
        _minutes("transit_lead_minutes", LEAD_MINUTES_MAX, nullable=True),
        _minutes("transit_duration_minutes", DURATION_MINUTES_MAX),
        _minutes("return_transit_minutes", DURATION_MINUTES_MAX),
        _minutes("post_buffer_minutes", DURATION_MINUTES_MAX),
        # The outbound leg would otherwise end after the anchor started, which is a journey
        # that arrives late by construction.
        CheckConstraint(
            "transit_lead_minutes IS NULL OR transit_lead_minutes >= transit_duration_minutes",
            name="the_outbound_leg_arrives_before_the_anchor",
        ),
        # Prep would otherwise still be running when the outbound leg left. The guard on a
        # non-zero prep duration is load-bearing: with no prep there is nothing to collide.
        CheckConstraint(
            "prep_duration_minutes = 0 OR "
            f"prep_lead_minutes >= prep_duration_minutes + {_EFFECTIVE_TRANSIT_LEAD}",
            name="prep_finishes_before_the_outbound_leg_leaves",
        ),
        # The three-way choice is explicit rather than encoded in whether a list happens to be
        # empty, so the list is non-empty for exactly one of the three scopes.
        CheckConstraint(
            "jsonb_typeof(forbidden_area_ids) = 'array' AND "
            f"(post_scope = '{FORBIDS_AREAS}') = (jsonb_array_length(forbidden_area_ids) > 0)",
            name="only_the_areas_scope_names_areas",
        ),
        CheckConstraint(
            f"jsonb_array_length(forbidden_area_ids) <= {FORBIDDEN_AREAS_MAX}",
            name="the_forbidden_areas_are_a_bounded_list",
        ),
        # A matched type is shown ON the anchor, so two types holding one name would leave a
        # reader unable to tell which rule fired.
        Index(
            f"uq_{ANCHOR_TYPES_TABLE}_{TENANT_ID_COLUMN}_name",
            TENANT_ID_COLUMN,
            "name",
            unique=True,
        ),
        # Every read of these is "this tenant's rules, in evaluation order".
        Index(
            f"ix_{ANCHOR_TYPES_TABLE}_{TENANT_ID_COLUMN}_rule_order",
            TENANT_ID_COLUMN,
            "rule_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(ANCHOR_TYPE_NAME_MAX_LENGTH), nullable=False)
    # Rules evaluate in this order and the first match wins. Not unique: a reorder rewrites
    # every position in one statement per row, and a unique constraint would reject the
    # intermediate states of any permutation that is not a rotation.
    rule_order: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    match_title_contains: Mapped[str | None] = mapped_column(
        String(MATCH_TITLE_MAX_LENGTH), nullable=True
    )
    # No foreign key, deliberately. See the module docstring.
    match_source_id: Mapped[UUID | None] = mapped_column(nullable=True)

    # PREP: a lead plus a duration, so a short block can sit hours ahead of the anchor.
    prep_lead_minutes: Mapped[int] = mapped_column(nullable=False)
    prep_duration_minutes: Mapped[int] = mapped_column(nullable=False)
    prep_area_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="SET NULL"), nullable=True
    )

    # TRANSIT: a lead plus a duration per leg. Null lead means abutting the anchor.
    transit_lead_minutes: Mapped[int | None] = mapped_column(nullable=True)
    transit_duration_minutes: Mapped[int] = mapped_column(nullable=False)
    return_transit_minutes: Mapped[int] = mapped_column(nullable=False)
    transit_area_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="SET NULL"), nullable=True
    )

    # RECOVERY: always a window, never a block, and always measured from the anchor's end.
    post_buffer_minutes: Mapped[int] = mapped_column(nullable=False)
    post_scope: Mapped[str] = mapped_column(String(max(len(scope) for scope in POST_SCOPES)))
    forbidden_area_ids: Mapped[list[str]] = mapped_column(JSONB(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Anchor(Base, TenantScoped):
    """One imported commitment: a fact, not a plan. Read-only in syncr."""

    __tablename__ = ANCHORS_TABLE
    __table_args__ = (
        # Half-open intervals, so a zero-length anchor cannot be stored. The adapter rejects
        # an event with no end before this is reached; this is what makes that unbypassable.
        CheckConstraint("ends_at > starts_at", name="an_anchor_occupies_time"),
        # THE RECONCILIATION KEY. Two sources publishing one UID are two anchors, because two
        # calendars can each carry the same meeting and excluding one must not remove the
        # other's occupancy.
        Index(
            f"uq_{ANCHORS_TABLE}_{TENANT_ID_COLUMN}_source_id_external_uid",
            TENANT_ID_COLUMN,
            "source_id",
            "external_uid",
            unique=True,
        ),
        # The span read the week view and the assembler both make.
        Index(f"ix_{ANCHORS_TABLE}_{TENANT_ID_COLUMN}_starts_at", TENANT_ID_COLUMN, "starts_at"),
        # Retyping persists on the SERIES, so every occurrence of one is written together.
        Index(f"ix_{ANCHORS_TABLE}_{TENANT_ID_COLUMN}_series_uid", TENANT_ID_COLUMN, "series_uid"),
        # Removing or re-evaluating a type reaches every anchor holding it.
        Index(
            f"ix_{ANCHORS_TABLE}_{TENANT_ID_COLUMN}_anchor_type_id",
            TENANT_ID_COLUMN,
            "anchor_type_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CALENDAR_SOURCES_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    external_uid: Mapped[str] = mapped_column(String(EXTERNAL_UID_MAX_LENGTH), nullable=False)
    # Set for an occurrence of a recurring series, which is what makes a retype reach all 250
    # standups rather than the one the user was looking at.
    series_uid: Mapped[str | None] = mapped_column(String(EXTERNAL_UID_MAX_LENGTH), nullable=True)
    title: Mapped[str] = mapped_column(String(ANCHOR_TITLE_MAX_LENGTH), nullable=False)
    # Absolute instants, and deliberately NOT snapped to the quarter hour: an imported anchor
    # is a fact and keeps its real time, even at :07.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Stored with NO reader. See `records.AnchorRecord`.
    location: Mapped[str | None] = mapped_column(String(ANCHOR_LOCATION_MAX_LENGTH), nullable=True)
    anchor_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{ANCHOR_TYPES_TABLE}.id", ondelete="SET NULL"), nullable=True
    )
    # True when the USER typed this occurrence, so a later rule match cannot undo it.
    type_overridden: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    # True when the source has been unreachable since this anchor was last confirmed. A failed
    # sync sets it; it never removes an anchor.
    possibly_stale: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
