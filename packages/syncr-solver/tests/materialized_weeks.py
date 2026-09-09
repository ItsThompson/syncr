"""Builders for one week of resolved inputs, shared by the materialization suites.

``materialize`` takes a fully resolved snapshot, so a test asserting one rule would otherwise
spell a week's worth of values it does not care about. These produce a legal week by default and
take overrides for the members under test.

Every value is real: the interval algebra, the identity derivation, the zone resolution, and each
domain value type are the shipped ones, and every document these produce is built through the
domain constructors rather than around them. A block whose id or binding was hand-written here
would be exactly the fixture a reader copies into a deserializer.

The week is 2026-W07, whose Monday is 09 February, and the zone is London, which is on GMT that
month. So a local wall time and its UTC spelling coincide, and an assertion about a rendered
``23:00`` is not also an assertion about an offset.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef, TransitLeg, date_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import (
    Anchor,
    AreaBudget,
    EntryBinding,
    FrameEntry,
    MaterializedEntry,
    Pin,
    ShadowBlock,
    SolveInputs,
)
from syncr_solver.state import SIZED_KINDS, PartialPlan, Placement, Sizing

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.zones import Date, ZoneId

WEEK = IsoWeek(2026, 7)
LONDON = "Europe/London"
MONDAY = WEEK.monday()
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
WEEK_MINUTES = 7 * 24 * 60

FITNESS: AreaId = UUID("00000000-0000-4000-8000-000000000001")
CAREER: AreaId = UUID("00000000-0000-4000-8000-000000000002")

# One content identity every generic candidate carries. A candidate's own content is not what most
# rules read, so it is stated once rather than per test.
A_TASK = UUID("00000000-0000-4000-8000-0000000000aa")
A_HABIT = UUID("00000000-0000-4000-8000-0000000000ab")


def at(hour: float, *, day: int = 0) -> datetime:
    """An instant this many hours into a day of the week, counted from its Monday midnight."""
    return MONDAY_MIDNIGHT + timedelta(days=day, hours=hour)


def between(start_hour: float, end_hour: float, *, day: int = 0) -> Interval:
    return Interval(at(start_hour, day=day), at(end_hour, day=day))


def on(day: int) -> Date:
    """The local date this many days into the week."""
    return WEEK.dates()[day]


def zones(*, zone: ZoneId = LONDON) -> dict[Date, ZoneId]:
    return dict.fromkeys(WEEK.dates(), zone)


def a_frame_entry(
    *,
    day: int = 0,
    interval: Interval | None = None,
    routine_id: UUID | None = None,
    title: str = "Sleep",
    min_duration_minutes: int = 6 * 60,
    flex_band_minutes: int = 30,
) -> FrameEntry:
    """One routine occurrence, keyed by the local date it materializes on."""
    return FrameEntry(
        routine_id=routine_id or uuid4(),
        occurrence_key=date_occurrence_key(on(day)),
        interval=interval or between(23, 31, day=day),
        min_duration_minutes=min_duration_minutes,
        flex_band_minutes=flex_band_minutes,
        title=title,
    )


def an_anchor(
    *,
    interval: Interval | None = None,
    anchor_id: UUID | None = None,
    title: str = "Kontron Placement Interview",
) -> Anchor:
    return Anchor(
        anchor_id=anchor_id or uuid4(),
        interval=interval or between(10, 11),
        title=title,
    )


def a_transit_block(
    *,
    anchor_id: UUID | None = None,
    leg: TransitLeg = TransitLeg.OUT,
    interval: Interval | None = None,
    area_id: AreaId = CAREER,
    title: str = "Leave for Uni",
    anchor_type_name: str = "Interview",
    anchor_title: str = "Kontron Placement Interview",
) -> ShadowBlock:
    return ShadowBlock(
        binding=BindingRef.for_anchor_transit(anchor_id or uuid4(), leg=leg),
        interval=interval or between(9.5, 10),
        area_id=area_id,
        title=title,
        anchor_type_name=anchor_type_name,
        anchor_title=anchor_title,
    )


def a_prep_block(
    *,
    anchor_id: UUID | None = None,
    interval: Interval | None = None,
    area_id: AreaId = CAREER,
    title: str = "Interview prep",
    anchor_type_name: str = "Interview",
    anchor_title: str = "Kontron Placement Interview",
) -> ShadowBlock:
    return ShadowBlock(
        binding=BindingRef.for_anchor_prep(anchor_id or uuid4()),
        interval=interval or between(8, 9),
        area_id=area_id,
        title=title,
        anchor_type_name=anchor_type_name,
        anchor_title=anchor_title,
    )


def a_concrete_entry(
    *,
    day: int = 0,
    entry_id: UUID | None = None,
    interval: Interval | None = None,
    area_id: AreaId = FITNESS,
    title: str = "Shower",
    day_type_name: str = "Weekday",
    target: BindingTarget = BindingTarget.HABIT,
    entity_id: UUID | None = None,
) -> MaterializedEntry:
    """A template entry whose content is named, so it becomes a block."""
    return MaterializedEntry(
        entry_id=entry_id or uuid4(),
        occurrence_key=date_occurrence_key(on(day)),
        kind=TemplateEntryKind.CONCRETE,
        interval=interval or between(6.75, 7, day=day),
        flex_band_minutes=0,
        area_id=area_id,
        day_type_name=day_type_name,
        title=title,
        binding=EntryBinding(target=target, entity_id=entity_id or uuid4()),
    )


def a_slot(
    *,
    day: int = 0,
    entry_id: UUID | None = None,
    interval: Interval | None = None,
    area_id: AreaId = FITNESS,
    day_type_name: str = "Weekday",
) -> MaterializedEntry:
    """A template entry whose content binds late, so it becomes an empty slot."""
    return MaterializedEntry(
        entry_id=entry_id or uuid4(),
        occurrence_key=date_occurrence_key(on(day)),
        kind=TemplateEntryKind.SLOT,
        interval=interval or between(18, 19, day=day),
        flex_band_minutes=15,
        area_id=area_id,
        day_type_name=day_type_name,
    )


def a_recovery_window(
    *,
    interval: Interval | None = None,
    scope: ForbiddenScope = ForbiddenScope.ALL,
    forbidden_area_ids: tuple[AreaId, ...] = (),
    anchor_id: UUID | None = None,
    label: str = "recovery · Kontron Placement Interview",
) -> ForbiddenWindow:
    return ForbiddenWindow(
        interval or between(11, 12),
        ForbiddenKind.RECOVERY,
        scope,
        forbidden_area_ids,
        label,
        anchor_id or uuid4(),
    )


def an_area_budget(
    *,
    area_id: AreaId = FITNESS,
    target_minutes: int = 0,
    floor_minutes: int = 0,
    name: str = "Fitness",
    max_per_day_minutes: int | None = None,
    floor_reservation_minutes: int | None = None,
    placed_minutes: int = 0,
    declared_floor_minutes: int | None = None,
) -> AreaBudget:
    """One Area's figures for the week, with the two floor quantities equal by default.

    They are equal on a week that holds no placement at all, which is what an empty fixture is: the
    solver's floor nets the immovable placements and the probe's reservation nets every placement,
    so both net nothing. A test about the difference between them states both.

    ``declared_floor_minutes`` defaults to the stated floors for the same reason: with nothing
    placed, neither netting has taken anything from the declared figure yet.
    """
    return AreaBudget(
        area_id=area_id,
        name=name,
        floor_minutes=floor_minutes,
        floor_reservation_minutes=(
            floor_minutes if floor_reservation_minutes is None else floor_reservation_minutes
        ),
        declared_floor_minutes=(
            floor_minutes if declared_floor_minutes is None else declared_floor_minutes
        ),
        target_minutes=target_minutes,
        placed_minutes=placed_minutes,
        max_per_day_minutes=max_per_day_minutes,
    )


def an_off_plan_period(
    *, interval: Interval, keep_frame: bool = False, label: str | None = None
) -> OffPlanPeriod:
    return OffPlanPeriod(interval=interval, keep_frame=keep_frame, label=label)


def inputs(**overrides: Any) -> SolveInputs:
    """One week of resolved inputs: empty by default, so a test states only what it drives."""
    stated: dict[str, Any] = {
        "iso_week": WEEK,
        "span": Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(days=7)),
        "now": NOW,
        "zone_by_date": zones(),
        "input_version": 3,
    }
    stated.update(overrides)
    return SolveInputs(**stated)


# --------------------------------------------------------------------------------
# What the constraint checker judges: a candidate, and the state it is judged against
# --------------------------------------------------------------------------------


def a_sizing(
    *,
    whole_minutes: int = 60,
    min_chunk_minutes: int = 15,
    splittable: bool = True,
) -> Sizing:
    return Sizing(
        whole_minutes=whole_minutes,
        min_chunk_minutes=min_chunk_minutes,
        splittable=splittable,
    )


def a_candidate(
    interval: Interval | None = None,
    *,
    title: str = "Shoulder & Arms",
    area_id: AreaId | None = FITNESS,
    binding: BindingRef | None = None,
    sizing: Sizing | None = None,
) -> Placement:
    """A candidate that breaks no rule on its own: a divisible task, on the grid, at its whole size.

    The sizing follows the span by default, so a test that varies only the span does not
    accidentally drive a sizing rule. A test driving one states its own.
    """
    span = interval or between(10, 11)
    reference = binding or BindingRef.for_task(A_TASK)
    return Placement(
        binding=reference,
        interval=span,
        title=title,
        area_id=area_id,
        sizing=_sizing_for(reference, span, sizing),
    )


def _sizing_for(binding: BindingRef, span: Interval, stated: Sizing | None) -> Sizing | None:
    """The sizing a candidate of this kind carries: the caller's, a default, or none at all."""
    if stated is not None or binding.kind not in SIZED_KINDS:
        return stated
    return a_sizing(whole_minutes=span.total_minutes())


def a_block(
    *,
    binding: BindingRef,
    interval: Interval | None = None,
    title: str = "Leetcode",
    area_id: AreaId | None = FITNESS,
) -> Block:
    """One block of this week's live plan, carrying the one clause a document requires."""
    return Block(
        iso_week=WEEK,
        interval=interval or between(10, 11),
        binding=binding,
        title=title,
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected=title),)),
        area_id=area_id,
    )


def a_live_plan(*blocks: Block) -> PlanDocument:
    """The plan the week currently holds, with figures a document will accept."""
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=zones(),
        discretionary_minutes=WEEK_MINUTES,
        unallocated_minutes=WEEK_MINUTES,
        oversubscription_minutes=0,
        blocks=blocks,
    )


def a_pin(
    *,
    binding: BindingRef | None = None,
    interval: Interval | None = None,
    day: int = 0,
    superseded_placement: Interval | None = None,
    objective_delta: float | None = None,
) -> Pin:
    return Pin(
        binding=binding or BindingRef.for_task(A_TASK),
        interval=interval or between(10, 11),
        pinned_on=on(day),
        superseded_placement=superseded_placement,
        objective_delta=objective_delta,
    )


def a_state(**overrides: Any) -> PartialPlan:
    """The state one week's inputs describe, which is what every rule is driven against."""
    return PartialPlan.of(inputs(**overrides))
