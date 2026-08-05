"""``SolveInputs.for_probe()``: a projection, and the three things it must not become.

The projection is where four consecutive reviews found the same defect, so this suite is stated
over the projection's inventory as much as over its values. Three claims carry the weight:

*It computes no netting.* The demands and the floor reservations arrive net from the assembler and
are carried forward verbatim, which these tests assert as identity rather than as equality where
the type allows it. A projection that re-derived either would put the probe's own quantity behind
a second rule, and the two consumers would disagree again.

*It splits the forbidden windows by scope, and nothing else does.* A window scoped to named Areas
is capacity for every other Area, so a whole-week figure that subtracted it would manufacture a
gap the week does not have.

*It pairs a pin with the block it pins.* A dragged block sits in the live plan where the solver
put it and in the pins where the user wants it, and the union of the two would occupy both.

The builders here are local rather than shared with the other suites in this package: this one is
about the struct's own projection, and a helper shaped for a materialization case would carry
fields that have nothing to do with it.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from syncr_domain.feasibility import ProbeInputs
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import (
    Anchor,
    AreaBudget,
    DeadlineDemand,
    FrameEntry,
    Pin,
    ShadowBlock,
    SolveInputs,
)

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant
    from syncr_domain.zones import Date, ZoneId

WEEK = IsoWeek(2026, 7)
LONDON: ZoneId = "Europe/London"
MONDAY = datetime(2026, 2, 9, tzinfo=UTC)
SPAN = Interval(MONDAY, MONDAY + timedelta(days=7))
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)

FITNESS: AreaId = UUID("eeeeeeee-0000-4000-8000-000000000001")
STUDY: AreaId = UUID("eeeeeeee-0000-4000-8000-000000000002")

# Which SolveInputs field each ProbeInputs field is projected from, declared so a field added to
# either struct has to be answered here. The capacity arithmetic reads thirteen of the twenty-one
# fields an assembly carries, and the eight it does not are named below.
PROJECTED_FROM = {
    "span": "span",
    "now": "now",
    "computed_at": "now",
    "input_version": "input_version",
    "frame": "frame",
    "anchors": "anchors",
    "absolute_forbidden": "forbidden_windows",
    "scoped_forbidden": "forbidden_windows",
    "off_plan": "off_plan",
    "placed": "live_plan",
    "area_floor_reservations": "areas",
    "area_targets": "areas",
    "deadline_demands": "deadline_demands",
}

# What the probe deliberately does not read, and why each is absent:
#
#   iso_week, zone_by_date   a rendering and a materialization question. The arithmetic is over
#                            instants, and no figure here needs a local date
#   frame_overhang           read THROUGH `frame`, because the night the preceding week spent is
#                            occupancy for the same reason this week's own occurrences are
#   shadow_blocks            allocated to an Area rather than removed from the week, so it reaches
#                            the probe through `placed` once a plan holds it
#   template_entries         content the solver places, not occupancy the probe subtracts
#   habit_occurrences        the same
#   eligible_tasks           the SOLVER's remaining-work figure. The probe reads its own demand
#   preferences              where work should go, which is a placement question
#   pins                     read THROUGH `placed`, paired with the blocks they pin
#   adjustments              already folded into the figures above
#   churn_baseline           what a re-solve is scored against
NOT_PROJECTED = frozenset(
    {
        "iso_week",
        "zone_by_date",
        "frame_overhang",
        "shadow_blocks",
        "template_entries",
        "habit_occurrences",
        "eligible_tasks",
        "preferences",
        "pins",
        "adjustments",
        "churn_baseline",
    }
)


def zones() -> dict[Date, ZoneId]:
    return dict.fromkeys(WEEK.dates(), LONDON)


def inputs(**overrides: object) -> SolveInputs:
    stated: dict[str, object] = {
        "iso_week": WEEK,
        "span": SPAN,
        "now": NOW,
        "zone_by_date": zones(),
        "input_version": 47,
    }
    stated.update(overrides)
    return SolveInputs(**stated)  # type: ignore[arg-type]


def a_budget(
    area_id: AreaId, *, name: str, reservation: int, floor: int, target: int
) -> AreaBudget:
    return AreaBudget(
        area_id=area_id,
        name=name,
        floor_minutes=floor,
        floor_reservation_minutes=reservation,
        target_minutes=target,
        placed_minutes=0,
    )


def a_window(interval: Interval, scope: ForbiddenScope, *areas: AreaId) -> ForbiddenWindow:
    return ForbiddenWindow(
        interval=interval,
        kind=ForbiddenKind.RECOVERY,
        scope=scope,
        forbidden_area_ids=areas,
        label="recovery · Kontron Interview",
        anchor_id=uuid4(),
    )


def a_frame_entry(interval: Interval) -> FrameEntry:
    return FrameEntry(
        routine_id=uuid4(),
        occurrence_key="2026-02-09",
        interval=interval,
        min_duration_minutes=360,
        flex_band_minutes=30,
        title="Sleep",
    )


def a_block(binding: BindingRef, interval: Interval) -> Block:
    return Block(
        iso_week=WEEK,
        interval=interval,
        binding=binding,
        title="Leetcode",
        area_id=FITNESS,
        reason=ReasonRecord(clauses=(Bound(source=BindingSource.QUEUE, selected="Leetcode"),)),
    )


def a_document(*blocks: Block) -> PlanDocument:
    """A live plan holding those blocks. The figures on it are not read by the projection."""
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=zones(),
        discretionary_minutes=10080,
        unallocated_minutes=0,
        oversubscription_minutes=0,
        blocks=blocks,
    )


def at(hour: int, *, day: int = 0, minute: int = 0) -> Instant:
    return MONDAY + timedelta(days=day, hours=hour, minutes=minute)


def spanning(start: int, end: int, *, day: int = 0) -> Interval:
    return Interval(at(start, day=day), at(end, day=day))


def test_the_projection_names_a_source_for_every_field_and_reads_nothing_else() -> None:
    # The inventory guard. A field added to either struct fails here, which is the moment to ask
    # whether the arithmetic needs it rather than the moment a verdict is wrong.
    projected = {field.name for field in dataclasses.fields(ProbeInputs)}
    assembled = {field.name for field in dataclasses.fields(SolveInputs)}

    assert set(PROJECTED_FROM) == projected
    assert set(PROJECTED_FROM.values()) <= assembled
    assert NOT_PROJECTED | set(PROJECTED_FROM.values()) == assembled


def test_a_demand_is_carried_forward_verbatim() -> None:
    # Identity rather than equality: the netted demand is the assembler's figure, and the one
    # mistake this projection must not make is deriving it again.
    demands = (
        DeadlineDemand(
            deadline=at(9, day=4),
            remaining_minutes=60,
            area_id=FITNESS,
            labels=("F&F Past Papers",),
        ),
    )

    assert inputs(deadline_demands=demands).for_probe().deadline_demands is demands


def test_a_floor_reservation_is_the_areas_own_figure_and_its_own_name() -> None:
    week = inputs(
        areas=(a_budget(FITNESS, name="Fitness", reservation=120, floor=300, target=900),)
    )

    reserved = week.for_probe().area_floor_reservations

    assert [(one.area_id, one.reserved_minutes, one.label) for one in reserved] == [
        (FITNESS, 120, "Fitness")
    ]


def test_the_projection_reads_the_probes_floor_quantity_and_not_the_solvers() -> None:
    # The two quantities differ exactly when a week holds unpinned placements, which is the normal
    # state of a solved week. Reading the solver's here reported a gap on every such week.
    week = inputs(areas=(a_budget(FITNESS, name="Fitness", reservation=0, floor=300, target=900),))

    assert week.for_probe().area_floor_reservations[0].reserved_minutes == 0


def test_a_target_is_carried_for_reporting_and_keyed_by_its_area() -> None:
    week = inputs(
        areas=(
            a_budget(FITNESS, name="Fitness", reservation=0, floor=300, target=900),
            a_budget(STUDY, name="Study", reservation=60, floor=120, target=420),
        )
    )

    assert week.for_probe().area_targets == {FITNESS: 900, STUDY: 420}


def test_a_window_forbidding_every_area_becomes_absolute_occupancy() -> None:
    week = inputs(forbidden_windows=(a_window(spanning(16, 18, day=2), ForbiddenScope.ALL),))

    projected = week.for_probe()

    assert projected.absolute_forbidden == IntervalSet([spanning(16, 18, day=2)])
    assert projected.scoped_forbidden == ()


def test_a_window_forbidding_named_areas_becomes_a_scoped_window_that_keeps_them() -> None:
    week = inputs(
        forbidden_windows=(a_window(spanning(16, 18, day=2), ForbiddenScope.AREAS, STUDY),)
    )

    projected = week.for_probe()

    assert projected.absolute_forbidden == IntervalSet()
    assert [window.forbidden_area_ids for window in projected.scoped_forbidden] == [(STUDY,)]
    assert projected.scoped_against(STUDY) == IntervalSet([spanning(16, 18, day=2)])
    assert projected.scoped_against(FITNESS) == IntervalSet()


def test_the_two_scopes_are_split_rather_than_one_of_them_being_dropped() -> None:
    week = inputs(
        forbidden_windows=(
            a_window(spanning(16, 18, day=2), ForbiddenScope.ALL),
            a_window(spanning(9, 11, day=3), ForbiddenScope.AREAS, STUDY),
        )
    )

    projected = week.for_probe()

    assert projected.absolute_forbidden == IntervalSet([spanning(16, 18, day=2)])
    assert [window.interval for window in projected.scoped_forbidden] == [spanning(9, 11, day=3)]


def test_the_frame_carries_the_night_the_preceding_week_spent() -> None:
    inherited = Interval(MONDAY, at(7))
    week = inputs(frame=(a_frame_entry(spanning(23, 25, day=1)),), frame_overhang=(inherited,))

    assert week.for_probe().frame == IntervalSet([inherited, spanning(23, 25, day=1)])


def test_an_anchor_reaches_the_probe_as_the_time_it_occupies() -> None:
    week = inputs(
        anchors=(
            Anchor(anchor_id=uuid4(), interval=spanning(16, 17, day=2), title="Kontron Interview"),
        )
    )

    assert week.for_probe().anchors == IntervalSet([spanning(16, 17, day=2)])


def test_an_off_plan_period_reaches_the_probe_as_the_time_it_suspends() -> None:
    week = inputs(off_plan=(OffPlanPeriod(interval=Interval(at(0, day=5), at(0, day=6))),))

    assert week.for_probe().off_plan == IntervalSet([Interval(at(0, day=5), at(0, day=6))])


def test_a_shadow_block_is_not_subtracted_from_the_week_it_is_allocated_in() -> None:
    # It carries an Area, so it is discretionary time allocated to that Area in the same way a
    # task is. Subtracting it would take the time out of the denominator AND charge it to an Area.
    week = inputs(
        shadow_blocks=(
            ShadowBlock(
                binding=BindingRef.for_task(uuid4()),
                interval=spanning(15, 16, day=2),
                area_id=FITNESS,
                title="Leave for Uni",
            ),
        )
    )

    projected = week.for_probe()

    assert projected.placed == IntervalSet()
    assert projected.absolute_forbidden == IntervalSet()


def test_the_committed_time_holds_every_live_plan_block_past_and_future() -> None:
    past, future = spanning(9, 10, day=1), spanning(9, 10, day=3)
    document = a_document(
        a_block(BindingRef.for_task(uuid4()), past),
        a_block(BindingRef.for_task(uuid4()), future),
    )

    assert inputs(live_plan=document).for_probe().placed == IntervalSet([past, future])


def test_a_pin_replaces_the_block_it_pins_rather_than_occupying_both_places() -> None:
    # The state every drag produces: the live plan still holds the block where the solver put it,
    # and the pin says where the user wants it. Unioned unpaired, the week loses an hour it has.
    binding = BindingRef.for_task(uuid4())
    document = a_document(a_block(binding, spanning(9, 10, day=3)))
    week = inputs(
        live_plan=document,
        pins=(Pin(binding=binding, interval=spanning(15, 16, day=3), pinned_on=WEEK.monday()),),
    )

    assert week.for_probe().placed == IntervalSet([spanning(15, 16, day=3)])


def test_a_pin_naming_a_binding_the_plan_no_longer_holds_is_committed_time_of_its_own() -> None:
    # The user's edit outlives a re-solve that dropped the block.
    week = inputs(
        pins=(
            Pin(
                binding=BindingRef.for_task(uuid4()),
                interval=spanning(15, 16, day=3),
                pinned_on=WEEK.monday(),
            ),
        )
    )

    assert week.for_probe().placed == IntervalSet([spanning(15, 16, day=3)])


def test_the_verdicts_instant_is_the_one_the_assembly_was_stamped_with() -> None:
    # No clock read: a verdict is a fact about one assembly, so two projections of it are equal
    # and a caller reproducing a failure gets the verdict that failure had.
    projected = inputs().for_probe()

    assert projected.computed_at == NOW
    assert projected.now == NOW
    assert projected.input_version == 47


def test_two_projections_of_one_assembly_are_equal() -> None:
    week = inputs(
        areas=(a_budget(FITNESS, name="Fitness", reservation=120, floor=300, target=900),),
        forbidden_windows=(a_window(spanning(16, 18, day=2), ForbiddenScope.AREAS, STUDY),),
    )

    assert week.for_probe() == week.for_probe()


def test_a_week_holding_nothing_projects_a_week_holding_nothing() -> None:
    projected = inputs().for_probe()

    assert projected.placed == IntervalSet()
    assert projected.area_floor_reservations == ()
    assert projected.deadline_demands == ()
    assert projected.scoped_forbidden == ()
