"""The probe over a real assembly: the floor split, and the pin that must change nothing.

These are the assertions that could not be made one layer down. The probe reads what the assembler
produces, so the property that closes the recurrence class -- that a pin cannot improve a verdict --
is only observable where the netting and the arithmetic meet. A test over literal probe inputs can
show the arithmetic is invariant under the transformation; only this tier can show the assembler
performs that transformation.

Three subjects:

*The floor split.* A healthy solved week is by definition one whose floors are met by solver-placed
blocks, and those are unpinned. The probe's reservation nets every placement, so such a week reports
nothing; the reservation that nets immovable placements only is the solver's, and reading it here
reported a six-hour gap on the normal state of the product.

*The pin.* Pinning a block where it already is changes which quantity the solver may re-place and
changes nothing the probe reads, so the verdict is identical. Moving it changes where the committed
time is, and the projection follows the pin rather than the plan.

*The agreement between the two statements of the pairing.* The projection unions the paired
intervals and the netting indexes the paired placements by task and by Area. Both pair a pin with
the block it pins; the two are crossed here rather than one being written in terms of the other.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from syncr_api.plans.netting import placements
from syncr_api.plans.verdicts import PROBE_DURATION, ProbeCaller, WeekProbe
from syncr_common.metrics import METHOD_DURATION
from syncr_domain.feasibility import Provenance, ShortfallKind, probe
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import IntervalSet
from syncr_domain.plan import AdjustmentKind
from tests.assembly_fakes import (
    NOW,
    WEEK,
    FakeAdjustments,
    FakeAreas,
    FakeOffPlan,
    FakePlacements,
    FakeRoutines,
    FakeTasks,
    a_pin,
    a_plan,
    a_routine,
    a_task,
    a_task_block,
    an_adjustment,
    an_area,
    an_assembler,
    an_off_plan_period,
    at,
    between,
)

if TYPE_CHECKING:
    from prometheus_client.samples import Sample

    from syncr_api.areas.records import AreaRecord
    from syncr_domain.feasibility import Verdict
    from syncr_domain.identifiers import TaskId
    from syncr_solver.inputs import SolveInputs

MINUTES_PER_HOUR = 60

# The bucket bound a histogram puts on its own per-bucket samples, which is not a label a caller
# chose and not one an alert may group by.
BUCKET_BOUND_LABEL = "le"

# Stable task identifiers, so a failure message names the same task on every run.
FITNESS_TASK: TaskId = UUID("f1f1f1f1-0000-4000-8000-000000000001")
CAREER_TASK: TaskId = UUID("f1f1f1f1-0000-4000-8000-000000000002")

# Wednesday 09:00 to Wednesday 19:00. Everything from 19:00 to the end of the week is declared off,
# so the capacity this week has left is exactly ten hours and every figure below is readable.
CAPACITY_MINUTES = 10 * MINUTES_PER_HOUR
# Wednesday 19:00 to the following Monday 00:00, as hours from the Wednesday's own midnight.
REST_OF_THE_WEEK = (19, 24 + 24 + 24 + 24 + 24)


def a_solved_week(
    *, fitness: AreaRecord, career: AreaRecord, pinned: BindingRef | None = None
) -> tuple[FakePlacements, FakeOffPlan]:
    """A week whose two floors are met entirely by unpinned solver-placed blocks.

    Five hours of Fitness from Wednesday 10:00 and three of Career after it, both strictly in the
    future and neither pinned, which is what the solver produces when it honours two floors. Two of
    the week's remaining ten hours stay genuinely uncommitted.

    The blocks start AFTER ``now`` rather than at it, and that is load-bearing: a block that has
    started is immovable, so a block beginning exactly at ``now`` would be netted from both floor
    quantities and the pair would agree here for the wrong reason.
    """
    gym = a_task_block(task_id=FITNESS_TASK, area_id=fitness.id, interval=between(10, 15, day=2))
    leetcode = a_task_block(task_id=CAREER_TASK, area_id=career.id, interval=between(15, 18, day=2))
    pins = () if pinned is None else (a_pin(binding=pinned, interval=between(10, 15, day=2)),)
    return (
        FakePlacements(live_plan=a_plan(blocks=[gym, leetcode]), pins=list(pins)),
        FakeOffPlan([an_off_plan_period(interval=between(*REST_OF_THE_WEEK, day=2))]),
    )


async def an_assembly(**overrides: object) -> SolveInputs:
    return await an_assembler(**overrides).assemble(WEEK, NOW)  # type: ignore[arg-type]


def kinds(verdict: Verdict) -> list[ShortfallKind]:
    return [shortfall.kind for shortfall in verdict.shortfalls]


async def test_a_week_whose_floors_are_met_by_unpinned_blocks_reports_no_floor_gap() -> None:
    # The floor rule, end to end. Fitness 5h and Career 3h, both met by unpinned solver-placed
    # blocks, with two of the week's remaining ten hours genuinely uncommitted.
    #
    # Under the superseded rule the probe read the solver's reservation, which nets IMMOVABLE
    # placements only. Neither block is immovable, so it reserved the whole 8h against 2h of free
    # capacity and reported a six-hour gap: on a healthy week, at amber panel volume, with
    # tradeoffs offered for it.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career", floor_hours=Decimal(3))
    placed, off_plan = a_solved_week(fitness=fitness, career=career)

    inputs = await an_assembly(
        areas=FakeAreas([fitness, career]), placements=placed, off_plan=off_plan
    )
    verdict = probe(inputs.for_probe())

    assert [one.reserved_minutes for one in inputs.for_probe().area_floor_reservations] == [0, 0]
    assert [area.floor_minutes for area in inputs.areas] == [300, 180]
    assert inputs.for_probe().placed.after(NOW).total_minutes() == 8 * MINUTES_PER_HOUR
    assert verdict.shortfalls == ()


async def test_pinning_an_already_placed_block_leaves_the_verdict_unchanged() -> None:
    # The assertion that catches the defect. Under the superseded rule, pinning a solver-placed
    # Fitness block moved it from movable to immovable, dropped the reservation by five hours while
    # free capacity was unchanged, and IMPROVED the verdict, which also made rejecting a proposed
    # move improve it.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career", floor_hours=Decimal(3))
    unpinned, off_plan = a_solved_week(fitness=fitness, career=career)
    pinned, _ = a_solved_week(
        fitness=fitness, career=career, pinned=BindingRef.for_task(FITNESS_TASK)
    )
    areas = FakeAreas([fitness, career])

    before = await an_assembly(areas=areas, placements=unpinned, off_plan=off_plan)
    after = await an_assembly(areas=areas, placements=pinned, off_plan=off_plan)

    assert probe(after.for_probe()) == probe(before.for_probe())
    # The solver's own floor figure DOES fall, and must: it has that much less left to place.
    assert [area.floor_minutes for area in after.areas] == [0, 180]


async def test_the_committed_time_follows_the_pin_rather_than_the_plan_it_overrides() -> None:
    # Every drag produces this state: the live plan holds the block where the solver put it and the
    # pin says where the user wants it. Unioned unpaired, the week would lose the hour twice.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    binding = BindingRef.for_task(FITNESS_TASK)
    placed = FakePlacements(
        live_plan=a_plan(
            blocks=[
                a_task_block(
                    task_id=FITNESS_TASK, area_id=fitness.id, interval=between(9, 10, day=3)
                )
            ]
        ),
        pins=[a_pin(binding=binding, interval=between(15, 16, day=3))],
    )

    inputs = await an_assembly(areas=FakeAreas([fitness]), placements=placed)

    assert inputs.for_probe().placed == IntervalSet([between(15, 16, day=3)])


async def test_the_projection_and_the_netting_pair_a_pin_with_its_block_the_same_way() -> None:
    # Two statements of one pairing, crossed against each other. The projection unions the paired
    # intervals; the netting indexes the paired placements. A change to either that dropped the
    # pairing would leave the probe's free capacity counting a different set from the demands and
    # reservations it is compared against, which is the defect class this pairing exists against.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    moved = BindingRef.for_task(FITNESS_TASK)
    placed = FakePlacements(
        live_plan=a_plan(
            blocks=[
                a_task_block(
                    task_id=FITNESS_TASK, area_id=fitness.id, interval=between(9, 10, day=3)
                ),
                a_task_block(
                    task_id=CAREER_TASK, area_id=fitness.id, interval=between(11, 12, day=3)
                ),
            ]
        ),
        pins=[a_pin(binding=moved, interval=between(15, 16, day=3))],
    )

    inputs = await an_assembly(areas=FakeAreas([fitness]), placements=placed)
    held = await placed.read(WEEK, inputs.span)
    paired = placements(held.live_plan, held.pins, now=NOW)

    assert inputs.for_probe().placed == IntervalSet(one.interval for one in paired)


async def test_a_deadline_the_week_cannot_reach_names_the_task_and_honors_the_other_floor() -> None:
    # The whole path, from a stored declaration to a rendered refusal: four hours of Career work due
    # on Thursday morning, one hour of capacity before it, and a Fitness floor that has nowhere
    # later to go because the rest of the week is off.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career")
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        title="F&F Past Papers",
        estimate_minutes=4 * MINUTES_PER_HOUR,
        deadline=at(10, day=2),
    )
    off_plan = FakeOffPlan([an_off_plan_period(interval=between(10, 24 * 5 + 24, day=2))])

    inputs = await an_assembly(
        areas=FakeAreas([fitness, career]), tasks=FakeTasks([task]), off_plan=off_plan
    )
    verdict = probe(inputs.for_probe())

    gap = next(one for one in verdict.shortfalls if one.kind is ShortfallKind.DEADLINE_CAPACITY)
    assert gap.against == ("F&F Past Papers",)
    assert gap.deadline == at(10, day=2)
    assert "the Fitness floor of 5h" in gap.honoring
    assert verdict.provenance is Provenance.PROBE
    assert not verdict.feasible


async def test_an_orphan_pins_two_hours_move_each_area_figure_by_120_clamped_at_zero() -> None:
    # The rule the two recorded gaps asked for. A pin whose binding the live plan no longer holds
    # takes its Area from its task, so each Fitness figure moves by the pin's two hours and the
    # clamps hold where the pinned minutes meet the declared floor.
    fitness = an_area(name="Fitness", floor_hours=Decimal(2))
    task = a_task(task_id=FITNESS_TASK, area_id=fitness.id)
    orphan = FakePlacements(
        live_plan=a_plan(blocks=[]),
        pins=[a_pin(binding=BindingRef.for_task(FITNESS_TASK), interval=between(10, 12, day=2))],
    )

    inputs = await an_assembly(
        areas=FakeAreas([fitness]), tasks=FakeTasks([task]), placements=orphan
    )

    budget = inputs.areas[0]
    assert budget.placed_minutes == 2 * MINUTES_PER_HOUR
    assert budget.floor_minutes == 0
    assert budget.floor_reservation_minutes == 0

    # The pair, on the week without the edit: nothing placed, both floors whole.
    untouched = await an_assembly(areas=FakeAreas([fitness]), tasks=FakeTasks([task]))

    assert untouched.areas[0].placed_minutes == 0
    assert untouched.areas[0].floor_minutes == 2 * MINUTES_PER_HOUR
    assert untouched.areas[0].floor_reservation_minutes == 2 * MINUTES_PER_HOUR


async def test_an_orphan_pin_no_longer_over_reports_the_floor_gap() -> None:
    # What the gap cost when it was open: free capacity lost the hour while no Area's reservation
    # netted it, so a week whose floor exactly fit reported a shortfall of exactly the pinned
    # hour. With the pin's Area resolved, the reservation nets the same hour the capacity gave
    # back, and the verdict reads the week the user committed to.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    task = a_task(task_id=FITNESS_TASK, area_id=fitness.id)
    # A week tight enough for the hour to matter: five hours of capacity from the stamped instant
    # against a five-hour floor, so without the pin the floor exactly fits.
    tight = FakeOffPlan([an_off_plan_period(interval=between(14, 24 * 4 + 24, day=2))])
    orphan = FakePlacements(
        live_plan=a_plan(blocks=[]),
        pins=[a_pin(binding=BindingRef.for_task(FITNESS_TASK), interval=between(10, 11, day=2))],
    )

    pinned = await an_assembly(
        areas=FakeAreas([fitness]), tasks=FakeTasks([task]), placements=orphan, off_plan=tight
    )
    unpinned = await an_assembly(
        areas=FakeAreas([fitness]), tasks=FakeTasks([task]), off_plan=tight
    )

    assert probe(unpinned.for_probe()).shortfalls == ()
    assert probe(pinned.for_probe()).shortfalls == ()


async def test_a_verdict_carries_the_version_and_the_instant_its_assembly_was_built_against() -> (
    None
):
    inputs = await an_assembly()

    verdict = probe(inputs.for_probe())

    assert verdict.computed_at == NOW
    assert verdict.input_version == inputs.input_version


async def test_a_routine_reduction_frees_capacity_the_area_targets_were_not_taken_over() -> None:
    # A measurement rather than a rule, and which of the two figures is right is open.
    #
    # The assembler takes the week's denominator over the frame BEFORE the concessions are folded,
    # and the snapshot carries the frame after. So a reduce_routine concession frees minutes the
    # probe reports as discretionary and no Area's target was computed over. Both figures are
    # asserted here, so whoever settles it has the number and the direction rather than an
    # argument, and so a change to either side is visible.
    #
    # 120 minutes a day off an eight-hour Sleep routine over seven days: 840 minutes.
    sleep = a_routine(
        duration_minutes=8 * MINUTES_PER_HOUR, min_duration_minutes=6 * MINUTES_PER_HOUR
    )
    reductions = {date.isoformat(): 2 * MINUTES_PER_HOUR for date in WEEK.dates()}
    fitness = an_area(name="Fitness", budget_percent=Decimal(100))

    inputs = await an_assembly(
        routines=FakeRoutines([sleep]),
        areas=FakeAreas([fitness]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=sleep.id,
                    reductions=reductions,
                )
            ]
        ),
    )
    verdict = probe(inputs.for_probe())

    # 2h off each of the week's seven nights, of which six fall inside the span: the seventh night's
    # reduction lands on the Monday after it, which this week does not hold.
    #
    #   the frame it carries      7 x 6h, plus 7h inherited from the week before = 49h,
    #                             of which 5h reach past the span's end
    #   inside the span           44h, so the probe's denominator is 168h - 44h = 124h
    #   unreduced, inside         56h, so every target was taken over 168h - 56h = 112h
    assert inputs.frame_occupancy().total_minutes() == 49 * MINUTES_PER_HOUR
    assert verdict.discretionary_minutes == 124 * MINUTES_PER_HOUR
    assert inputs.areas[0].target_minutes == 112 * MINUTES_PER_HOUR
    assert verdict.discretionary_minutes - inputs.areas[0].target_minutes == 12 * MINUTES_PER_HOUR


async def test_a_probe_observes_its_duration_under_its_own_callers_label() -> None:
    inputs = await an_assembly()
    before = _observations(ProbeCaller.MAINTAINER)

    WeekProbe(caller=ProbeCaller.MAINTAINER).verdict_for(inputs)

    assert _observations(ProbeCaller.MAINTAINER) == before + 1


async def test_the_probe_histogram_carries_the_caller_and_no_other_label() -> None:
    # Read as a scraper reads it, so the label set the alert is written against is the one exposed.
    for caller in ProbeCaller:
        PROBE_DURATION.labels(caller=caller.value).observe(0.0)

    labels = {
        tuple(sorted(set(sample.labels) - {BUCKET_BOUND_LABEL}))
        for sample in _probe_samples()
        if sample.labels
    }
    values = {sample.labels["caller"] for sample in _probe_samples() if sample.labels}

    assert labels == {("caller",)}
    assert values == {caller.value for caller in ProbeCaller}


async def test_a_measured_probe_also_carries_the_per_method_latency_every_component_has() -> None:
    inputs = await an_assembly()
    before = _method_observations("feasibility", "verdict_for")

    WeekProbe(caller=ProbeCaller.REQUEST).verdict_for(inputs)

    assert _method_observations("feasibility", "verdict_for") == before + 1


async def test_a_measured_probe_returns_the_same_verdict_the_arithmetic_does() -> None:
    # The wrapper measures and binds a label. It must not be a second reading of the week.
    inputs = await an_assembly()

    assert WeekProbe(caller=ProbeCaller.REQUEST).verdict_for(inputs) == probe(inputs.for_probe())


def _probe_samples() -> list[Sample]:
    return [sample for metric in PROBE_DURATION.collect() for sample in metric.samples]


def _observations(caller: ProbeCaller) -> float:
    """How many verdicts this caller's histogram has recorded, read from its own samples."""
    return _count_in(PROBE_DURATION.collect(), {"caller": caller.value})


def _method_observations(component: str, method: str) -> float:
    """How many calls the per-method histogram has recorded for one component and method."""
    return _count_in(METHOD_DURATION.collect(), {"component": component, "method": method})


def _count_in(collected: object, labels: dict[str, str]) -> float:
    return next(
        (
            sample.value
            for metric in collected  # type: ignore[attr-defined]
            for sample in metric.samples
            if sample.name.endswith("_count")
            and all(sample.labels.get(name) == value for name, value in labels.items())
        ),
        0.0,
    )
