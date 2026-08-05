"""Builders for the plan values the projection reads: blocks, gaps, and whole documents.

A block needs a week, an interval, a binding, a title and a reason before it exists at all, so a
test asserting one projection rule would otherwise spell four values it does not care about. These
produce valid values by default and take overrides for the field under test.

They live here rather than inside one suite because more than one suite builds a document, and a
builder imported from a test module couples the two suites: the domain's own
``syncr-domain/tests/plan_values.py`` exists for the same reason one package over, and cannot be
imported from this member.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syncr_domain.gaps import (
    EmptySlot,
    EmptySlotReason,
    ForbiddenKind,
    ForbiddenScope,
    ForbiddenWindow,
)
from syncr_domain.identity import (
    BindingKind,
    BindingRef,
    Origin,
    TransitLeg,
    binding_kind_of,
    origin_of,
)
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, DerivationSource, ReasonRecord
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_domain.zones import Date, ZoneId

LONDON: ZoneId = "Europe/London"

WEEK = IsoWeek(2026, 7)
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)

CAREER = uuid4()
FITNESS = uuid4()
INTERVIEW = uuid4()

A_BOUND_REASON = ReasonRecord((Bound(DerivationSource.ROUTINE, "Sleep · 23:00 + 8h"),))

ORIGINS_WITHOUT_AN_AREA = frozenset({Origin.FRAME, Origin.ANCHOR})


def at(hour: float, *, day: int = 0, week: IsoWeek = WEEK) -> datetime:
    """An instant so many hours into a day of ``week``, counted from its Monday midnight UTC."""
    monday = datetime.combine(week.monday(), datetime.min.time(), tzinfo=UTC)
    return monday + timedelta(days=day, hours=hour)


def between(start_hour: float, end_hour: float, *, day: int = 0, week: IsoWeek = WEEK) -> Interval:
    return Interval(at(start_hour, day=day, week=week), at(end_hour, day=day, week=week))


def a_binding(kind: BindingKind, *, week: IsoWeek = WEEK) -> BindingRef:
    """One legal binding per kind, each keyed the way its own derivation keys it."""
    match kind:
        case BindingKind.ROUTINE:
            return BindingRef.for_routine(uuid4(), on=week.monday())
        case BindingKind.TEMPLATE_ENTRY:
            return BindingRef.for_template_entry(uuid4(), on=week.monday())
        case BindingKind.HABIT:
            return BindingRef.for_habit(uuid4(), index=0)
        case BindingKind.TASK:
            return BindingRef.for_task(uuid4())
        case BindingKind.ANCHOR:
            return BindingRef.for_anchor(INTERVIEW)
        case BindingKind.ANCHOR_PREP:
            return BindingRef.for_anchor_prep(INTERVIEW)
        case BindingKind.ANCHOR_TRANSIT:
            return BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.OUT)


def a_block(origin: Origin = Origin.HABIT, **overrides: Any) -> Block:
    """A block of one origin, carrying an Area exactly when that origin requires one."""
    week: IsoWeek = overrides.pop("week", WEEK)
    fields: dict[str, Any] = {
        "iso_week": week,
        "interval": between(9, 10, week=week),
        "binding": a_binding(binding_kind_of(origin), week=week),
        "title": f"{origin.value} · something",
        "reason": A_BOUND_REASON,
        "area_id": None if origin in ORIGINS_WITHOUT_AN_AREA else CAREER,
    }
    return Block(**(fields | overrides))


def a_block_holding(binding: BindingRef, interval: Interval, **overrides: Any) -> Block:
    """One block of the content ``binding`` names, at ``interval``.

    The origin follows from the binding's kind through the domain's own mapping, so a suite
    pairing two documents states the identity once and the block's own vocabulary is derived.
    """
    return a_block(origin_of(binding.kind), binding=binding, interval=interval, **overrides)


def a_window(**overrides: Any) -> ForbiddenWindow:
    """A recovery window forbidding one Area, which is the case the interface renders."""
    fields: dict[str, Any] = {
        "interval": between(16.75, 18),
        "kind": ForbiddenKind.RECOVERY,
        "scope": ForbiddenScope.AREAS,
        "forbidden_area_ids": (CAREER,),
        "label": "recovery · Kontron Interview",
        "anchor_id": INTERVIEW,
    }
    return ForbiddenWindow(**(fields | overrides))


def a_slot(**overrides: Any) -> EmptySlot:
    """An unfilled Area slot in the evening, whose backlog held nothing eligible."""
    fields: dict[str, Any] = {
        "interval": between(19, 20),
        "area_id": CAREER,
        "reason": EmptySlotReason.NO_ELIGIBLE_CONTENT,
    }
    return EmptySlot(**(fields | overrides))


def a_zone_map(week: IsoWeek = WEEK, zone: ZoneId = LONDON) -> dict[Date, ZoneId]:
    """One zone per day of the week, which is what a document requires."""
    return dict.fromkeys(week.dates(), zone)


def a_document(**overrides: Any) -> PlanDocument:
    """A week with one habit block, its figures consistent, and every day's zone stated."""
    week: IsoWeek = overrides.pop("week", WEEK)
    fields: dict[str, Any] = {
        "iso_week": week,
        "zone_by_date": a_zone_map(week),
        "discretionary_minutes": 6000,
        "unallocated_minutes": 120,
        "oversubscription_minutes": 0,
        "blocks": (a_block(week=week),),
    }
    return PlanDocument(**(fields | overrides))
