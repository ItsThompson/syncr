"""Builders for the plan value types, shared by the suites that assemble a week.

A block needs a week, an interval, a binding, a title, and a reason before it exists at all,
so a test asserting one rule would otherwise spell four values it does not care about. These
produce valid values by default and take overrides for the one field under test.

They live beside ``instants.py`` rather than inside one suite, because the document suite and
the gap suite both build blocks, and a builder imported from a test module couples one suite
to the other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syncr_domain.fixtures.dst_weeks import LONDON
from syncr_domain.gaps import (
    EmptySlot,
    EmptySlotReason,
    ForbiddenKind,
    ForbiddenScope,
    ForbiddenWindow,
)
from syncr_domain.identity import BindingKind, BindingRef, Origin, TransitLeg, binding_kind_of
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, DerivationSource, ReasonRecord
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from uuid import UUID

    from syncr_domain.zones import Date, ZoneId

WEEK = IsoWeek(2026, 7)
MONDAY = WEEK.monday()
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)

CAREER = uuid4()
INTERVIEW = uuid4()

A_REASON = ReasonRecord((Bound(DerivationSource.ROUTINE, "Sleep · 23:00 + 8h"),))

ORIGINS_WITHOUT_AN_AREA = frozenset({Origin.FRAME, Origin.ANCHOR})


def at(hour: float, *, day: int = 0) -> datetime:
    return MONDAY_MIDNIGHT + timedelta(days=day, hours=hour)


def between(start_hour: float, end_hour: float, *, day: int = 0) -> Interval:
    return Interval(at(start_hour, day=day), at(end_hour, day=day))


def a_binding(kind: BindingKind = BindingKind.HABIT, **overrides: Any) -> BindingRef:
    """One legal binding per kind, so a per-origin rule can be asserted over all seven.

    Each kind takes different overrides, because each named constructor does, and an override no
    branch forwards is refused rather than dropped: a test reading "a habit on Thursday" would
    otherwise assert about Monday and pass.
    """
    entity_id = overrides.pop("entity_id", uuid4())
    binding = _a_binding_of(kind, entity_id, overrides)
    if overrides:
        raise TypeError(f"a {kind.value!r} binding takes no {', '.join(sorted(overrides))}")
    return binding


def _a_binding_of(kind: BindingKind, entity_id: UUID, overrides: dict[str, Any]) -> BindingRef:
    match kind:
        case BindingKind.ROUTINE:
            return BindingRef.for_routine(entity_id, on=overrides.pop("on", MONDAY))
        case BindingKind.TEMPLATE_ENTRY:
            return BindingRef.for_template_entry(entity_id, on=overrides.pop("on", MONDAY))
        case BindingKind.HABIT:
            return BindingRef.for_habit(entity_id, index=overrides.pop("index", 0))
        case BindingKind.TASK:
            return BindingRef.for_task(entity_id, split_index=overrides.pop("split_index", None))
        case BindingKind.ANCHOR:
            return BindingRef.for_anchor(entity_id)
        case BindingKind.ANCHOR_PREP:
            return BindingRef.for_anchor_prep(entity_id)
        case BindingKind.ANCHOR_TRANSIT:
            return BindingRef.for_anchor_transit(
                entity_id, leg=overrides.pop("leg", TransitLeg.OUT)
            )


def a_block(**overrides: Any) -> Block:
    """A habit block on Monday morning, carrying the Area a habit block has to carry."""
    fields: dict[str, Any] = {
        "iso_week": WEEK,
        "interval": between(6, 7.5),
        "binding": a_binding(),
        "title": "Gym · Legs",
        "reason": A_REASON,
        "area_id": CAREER,
    }
    return Block(**(fields | overrides))


def a_block_of(origin: Origin, **overrides: Any) -> Block:
    """A block of one origin, with or without an Area as that origin requires."""
    fields: dict[str, Any] = {
        "binding": a_binding(binding_kind_of(origin)),
        "area_id": None if origin in ORIGINS_WITHOUT_AN_AREA else CAREER,
    }
    return a_block(**(fields | overrides))


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


def a_zone_map(zone: ZoneId = LONDON) -> dict[Date, ZoneId]:
    """One zone for each of the week's seven dates, which is what a document requires."""
    return dict.fromkeys(WEEK.dates(), zone)


def a_document(**overrides: Any) -> PlanDocument:
    """A week with one block, its figures consistent, and every day's zone stated."""
    fields: dict[str, Any] = {
        "iso_week": WEEK,
        "zone_by_date": a_zone_map(),
        "discretionary_minutes": 6000,
        "unallocated_minutes": 120,
        "oversubscription_minutes": 0,
        "blocks": (a_block(),),
    }
    return PlanDocument(**(fields | overrides))
