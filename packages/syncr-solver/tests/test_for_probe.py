"""``SolveInputs.for_probe()``: a projection, and the four things it must not become.

The projection is where four consecutive reviews found the same defect, so this suite is stated
over the projection's inventory as much as over its values. Four claims carry the weight:

*It computes no netting.* The demands and the floor reservations arrive net from the assembler and
are carried forward verbatim, which these tests assert as identity rather than as equality where
the type allows it. A projection that re-derived either would put the probe's own quantity behind
a second rule, and the two consumers would disagree again.

*It splits the forbidden windows by scope, and nothing else does.* A window scoped to named Areas
is capacity for every other Area, so a whole-week figure that subtracted it would manufacture a
gap the week does not have.

*It pairs a pin with the block it pins.* A dragged block sits in the live plan where the solver
put it and in the pins where the user wants it, and the union of the two would occupy both.

*It carries the probe's quantity rather than the solver's, on every field where the two net
different sets.* Three fields got that wrong and each was corrected after it shipped, by a reader.
The generated property at the end of this file re-derives all three conclusions on every run and
extends them to any field added later. It draws weeks whose live plan holds unpinned placements
ahead of ``now``, which is the only state in which a wrong carry is observable at all, and a state
no literal fixture reaches by accident.

The builders here are local rather than shared with the other suites in this package: this one is
about the struct's own projection, and a helper shaped for a materialization case would carry
fields that have nothing to do with it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import islice
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from syncr_domain.discretionary import discretionary_intervals
from syncr_domain.feasibility import FloorReservation, ProbeInputs, ScopedWindow
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.tasks import Priority
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import (
    Anchor,
    AreaBudget,
    DeadlineDemand,
    EligibleTask,
    FrameEntry,
    Pin,
    ShadowBlock,
    SolveInputs,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

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
# A third Area, so a scoped window can forbid one Area while the placements the two nettings
# disagree about sit in another.
CAREER: AreaId = UUID("eeeeeeee-0000-4000-8000-000000000003")
AREA_POOL = ((FITNESS, "Fitness"), (STUDY, "Study"), (CAREER, "Career"))

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
#   dropped_legs             the same reading from the other side: a dropped journey allocates
#                            nothing, so its span stays discretionary and needs no projection
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
        "dropped_legs",
        "template_entries",
        "habit_occurrences",
        "eligible_tasks",
        "preferences",
        "pins",
        "adjustments",
        "churn_baseline",
    }
)

# The two projected fields the projection hands over as the very object the assembly holds, rather
# than as a value built from it. Asserted by identity, because a re-derivation producing an equal
# value would satisfy an equality check and re-deriving the netted demand is the one mistake this
# projection must not make.
#
# The instants are not here, and the reason is not that they are safe. ``ProbeInputs`` re-normalizes
# both of them through ``as_instant``, which is ``astimezone(UTC)``, and that returns the same
# object for an already-UTC datetime only by CPython's matching-zone fast path. Identity there would
# pin an interpreter detail rather than anything about this projection, so an equal copy of an
# instant goes uncaught here and a wrong one does not.
CARRIED_BY_IDENTITY = frozenset({"span", "deadline_demands"})


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
    area_id: AreaId, *, name: str, reservation: int, floor: int, target: int, placed: int = 0
) -> AreaBudget:
    return AreaBudget(
        area_id=area_id,
        name=name,
        floor_minutes=floor,
        floor_reservation_minutes=reservation,
        target_minutes=target,
        placed_minutes=placed,
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


def a_block(
    binding: BindingRef,
    interval: Interval,
    *,
    area_id: AreaId = FITNESS,
    split_count: int | None = None,
) -> Block:
    return Block(
        iso_week=WEEK,
        interval=interval,
        binding=binding,
        title="Leetcode",
        area_id=area_id,
        split_count=split_count,
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


# Where a generated week lays each kind of interval out, as hours from Monday. Disjoint by
# construction: every netting below is a sum of durations while the projection's sets merge
# overlaps, so an overlapping draw would make one side of an equality lose minutes the other keeps.
#
#   [0h, 7h]      the night inherited from the preceding week
#   [8h, 57h)     placements behind `now`, which is Wednesday 09:00
#   [58h, 103h)   placements ahead of it, two slots each so a drag can move one
#   [110h, 114h)  one deadline per task, after every placement and inside the week
#   [120h, 147h)  the frame, the anchors, the windows, off-plan, and the shadow blocks
OVERHANG_MAX_QUARTERS = 28
PAST_FROM = at(8)
FUTURE_FROM = at(58)
DEADLINE_FROM = at(110)
OCCUPANCY_FROM = at(120)

# Whole quarter hours, because the product snaps to them and every figure here is minutes. An
# off-plan period refuses bounds off that grid, so the air between two laid-out intervals is a
# quarter hour rather than a minute.
QUARTER_MINUTES = 15
DURATIONS = st.integers(min_value=1, max_value=8).map(lambda quarters: quarters * QUARTER_MINUTES)

MAX_TASKS = 4
MAX_DRAWN_PLACEMENTS = 6
MAX_OCCURRENCES = 2

# Enough to exercise the shapes rather than to hunt a rare counterexample. Every draw already holds
# every state the pairing tells apart, so a wrong carry reddens on the first example rather than on
# a lucky one, and the figure buys variety in the counts and the distribution instead of reach.
PROJECTION_EXAMPLES = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class PlacementState:
    """One of the states a week's committed time comes in, as the two nettings read it.

    ``blocked`` is whether the live plan holds it, ``pinned`` whether the user's own edit does, and
    ``past`` whether it sits behind ``now``. A state can carry both of the first two because a pin
    and the block it pins are ONE placement, at the pin's interval.
    """

    reading: str
    blocked: bool
    pinned: bool
    past: bool

    @property
    def is_immovable(self) -> bool:
        """Whether the solver's netting subtracts it: the user pinned it, or it already happened."""
        return self.pinned or self.past


# Every state committed time comes in. The second is the one the two nettings disagree about, and
# the property's non-vacuity assertion is what keeps a generator that stopped emitting it visible.
STATES = (
    PlacementState(reading="a block behind now", blocked=True, pinned=False, past=True),
    PlacementState(
        reading="an unpinned block ahead of now", blocked=True, pinned=False, past=False
    ),
    PlacementState(
        reading="a dragged block, in the plan and in a pin", blocked=True, pinned=True, past=False
    ),
    PlacementState(
        reading="a pin the plan no longer holds", blocked=False, pinned=True, past=False
    ),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Placement:
    """One thing a generated week has already committed to, and which Area it is charged to.

    ``interval`` is where the week actually holds it, which is the pin's interval whenever a pin
    holds it: a dragged block sits where the user put it rather than in both places.
    """

    state: PlacementState
    area_id: AreaId
    interval: Interval
    block: Block | None
    pin: Pin | None

    @property
    def minutes(self) -> int:
        return self.interval.total_minutes()


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedTask:
    """One task the week owes work on, with every placement it already holds toward that work."""

    task_id: UUID
    title: str
    area_id: AreaId
    deadline: Instant
    estimate_minutes: int
    placements: tuple[Placement, ...]

    @property
    def binding(self) -> BindingRef:
        """What the solver's eligibility is keyed by, which is the task rather than one chunk."""
        return BindingRef.for_task(self.task_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedArea:
    """One Area's declared figures, before either netting is applied to the floor."""

    area_id: AreaId
    name: str
    declared_floor_minutes: int
    target_minutes: int


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedWeek:
    """A drawn week: the assembly, and the intent it was assembled from.

    The assertions are stated against the intent. An expectation read back out of the assembly
    through the projection's own helpers would assert only that the projection equals itself, and
    the scope split and the pin pairing are exactly the two choices worth catching.
    """

    inputs: SolveInputs
    areas: tuple[GeneratedArea, ...]
    tasks: tuple[GeneratedTask, ...]
    absolute_windows: tuple[Interval, ...]
    scoped_windows: tuple[ScopedWindow, ...]

    @property
    def placements(self) -> tuple[Placement, ...]:
        return tuple(placement for task in self.tasks for placement in task.placements)


def placements_in(tasks: Iterable[GeneratedTask], area_id: AreaId) -> tuple[Placement, ...]:
    return tuple(one for task in tasks for one in task.placements if one.area_id == area_id)


def minutes_of(placements: Iterable[Placement]) -> int:
    return sum(placement.minutes for placement in placements)


def immovable(placements: Iterable[Placement]) -> tuple[Placement, ...]:
    """What the SOLVER's netting subtracts: the pins, and everything already behind ``now``."""
    return tuple(one for one in placements if one.state.is_immovable)


def movable(placements: Iterable[Placement]) -> tuple[Placement, ...]:
    """The unpinned placements ahead of ``now``: the whole difference between the two nettings."""
    return tuple(one for one in placements if not one.state.is_immovable)


def laid_out(start: Instant, minutes: Sequence[int]) -> tuple[Interval, ...]:
    """One interval per duration, in order from ``start``, with a quarter hour of air between."""
    laid: list[Interval] = []
    cursor = start
    for duration in minutes:
        end = cursor + timedelta(minutes=duration)
        laid.append(Interval(cursor, end))
        cursor = end + timedelta(minutes=QUARTER_MINUTES)
    return tuple(laid)


def a_placement(
    state: PlacementState,
    *,
    binding: BindingRef,
    area_id: AreaId,
    chunks: int | None,
    behind: Interval,
    ahead: tuple[Interval, Interval],
) -> Placement:
    """One placement in that state, in the slots the week reserved for it.

    A dragged block takes both of the pair, at one duration in two places, because a pin whose
    interval matched the block it pins would make the pairing invisible to a set of intervals.
    """
    where = behind if state.past else ahead[0]
    block = a_block(binding, where, area_id=area_id, split_count=chunks) if state.blocked else None
    pin = Pin(binding=binding, interval=ahead[1], pinned_on=WEEK.monday()) if state.pinned else None
    return Placement(
        state=state,
        area_id=area_id,
        interval=where if pin is None else pin.interval,
        block=block,
        pin=pin,
    )


@st.composite
def weeks_holding_unpinned_placements(draw: st.DrawFn) -> GeneratedWeek:
    """A week whose live plan holds at least one unpinned placement ahead of ``now``.

    Every state committed time comes in is present in every draw, plus a drawn tail of them, so no
    assertion rests on a draw happening to reach the one state in which the two nettings differ.

    **The assembler's netting is modeled here**, because carrying its result forward is what the
    projection is asserted to do: one declared floor is netted twice and one estimate is netted
    twice, against the two placement sets. So what the property is about is which of each pair the
    projection reads. Whether the netting itself is right is the assembler's own suite.
    """
    pool = draw(
        st.lists(st.sampled_from(AREA_POOL), min_size=1, max_size=len(AREA_POOL), unique=True)
    )
    task_areas = draw(st.lists(st.sampled_from(pool), min_size=1, max_size=MAX_TASKS))
    drawn = draw(st.lists(st.sampled_from(STATES), max_size=MAX_DRAWN_PLACEMENTS))
    states = draw(st.permutations([*STATES, *drawn]))
    owners = draw(
        st.lists(
            st.integers(min_value=0, max_value=len(task_areas) - 1),
            min_size=len(states),
            max_size=len(states),
        )
    )
    durations = draw(st.lists(DURATIONS, min_size=len(states), max_size=len(states)))
    behind = laid_out(PAST_FROM, durations)
    ahead = laid_out(FUTURE_FROM, [minutes for minutes in durations for _ in range(2)])

    owned: dict[int, list[int]] = {index: [] for index in range(len(task_areas))}
    for slot, owner in enumerate(owners):
        owned[owner].append(slot)

    tasks: list[GeneratedTask] = []
    for index, (area_id, _) in enumerate(task_areas):
        slots = owned[index]
        divided = len(slots) > 1
        task_id = uuid4()
        placements = tuple(
            a_placement(
                states[slot],
                binding=BindingRef.for_task(task_id, split_index=position if divided else None),
                area_id=area_id,
                chunks=len(slots) if divided else None,
                behind=behind[slot],
                ahead=(ahead[2 * slot], ahead[2 * slot + 1]),
            )
            for position, slot in enumerate(slots)
        )
        tasks.append(
            GeneratedTask(
                task_id=task_id,
                title=f"Task {index}",
                area_id=area_id,
                # After every placement and distinct per task, so one demand is one task: several
                # tasks sharing one deadline in one Area are one demand, and "per task" would then
                # name a group rather than a task.
                deadline=DEADLINE_FROM + timedelta(hours=index),
                estimate_minutes=minutes_of(placements) + draw(DURATIONS),
                placements=placements,
            )
        )

    areas: list[GeneratedArea] = []
    for area_id, name in pool:
        here = tuple(one for task in tasks for one in task.placements if one.area_id == area_id)
        areas.append(
            GeneratedArea(
                area_id=area_id,
                name=name,
                # Above every placement in the Area, so neither netting is clamped at zero: a clamp
                # collapses the difference the property is stated over into an inequality.
                declared_floor_minutes=minutes_of(here) + draw(DURATIONS),
                target_minutes=draw(st.integers(min_value=0, max_value=20 * 60)),
            )
        )

    frame_count = draw(st.integers(min_value=0, max_value=MAX_OCCURRENCES))
    anchor_count = draw(st.integers(min_value=0, max_value=MAX_OCCURRENCES))
    off_plan_count = draw(st.integers(min_value=0, max_value=MAX_OCCURRENCES))
    absolute_count = draw(st.integers(min_value=0, max_value=MAX_OCCURRENCES))
    # At least one of each: a scoped window has to be shown NOT to leave the whole-week figure, and
    # a shadow block has to be somewhere for a projection that started subtracting one to be seen.
    scoped_count = draw(st.integers(min_value=1, max_value=MAX_OCCURRENCES))
    shadow_count = draw(st.integers(min_value=1, max_value=MAX_OCCURRENCES))
    counted = (
        frame_count + anchor_count + off_plan_count + absolute_count + scoped_count + shadow_count
    )
    supply = iter(
        laid_out(OCCUPANCY_FROM, draw(st.lists(DURATIONS, min_size=counted, max_size=counted)))
    )
    frame = tuple(islice(supply, frame_count))
    anchored = tuple(islice(supply, anchor_count))
    suspended = tuple(islice(supply, off_plan_count))
    absolute_windows = tuple(islice(supply, absolute_count))
    scoped_intervals = tuple(islice(supply, scoped_count))
    shadowed = tuple(islice(supply, shadow_count))

    scoped_windows: list[ScopedWindow] = []
    for interval in scoped_intervals:
        forbidden = draw(st.lists(st.sampled_from(pool), min_size=1, unique=True))
        scoped_windows.append(
            ScopedWindow(
                interval=interval, forbidden_area_ids=tuple(area_id for area_id, _ in forbidden)
            )
        )

    inherited = draw(st.integers(min_value=0, max_value=OVERHANG_MAX_QUARTERS)) * QUARTER_MINUTES
    overhang = () if inherited == 0 else (Interval(MONDAY, MONDAY + timedelta(minutes=inherited)),)

    # The two floor quantities, netted from one declared figure against the two placement sets. This
    # is the assembler's arithmetic, and which of the pair the projection reads is the subject.
    budgets: list[AreaBudget] = []
    for area in areas:
        charged = placements_in(tasks, area.area_id)
        budgets.append(
            a_budget(
                area.area_id,
                name=area.name,
                reservation=area.declared_floor_minutes - minutes_of(charged),
                floor=area.declared_floor_minutes - minutes_of(immovable(charged)),
                target=area.target_minutes,
                placed=minutes_of(charged),
            )
        )

    return GeneratedWeek(
        inputs=inputs(
            input_version=draw(st.integers(min_value=1, max_value=10_000)),
            frame=tuple(a_frame_entry(interval) for interval in frame),
            frame_overhang=overhang,
            anchors=tuple(
                Anchor(anchor_id=uuid4(), interval=interval, title="Kontron Interview")
                for interval in anchored
            ),
            shadow_blocks=tuple(
                ShadowBlock(
                    binding=BindingRef.for_anchor_prep(uuid4()),
                    interval=interval,
                    area_id=pool[0][0],
                    title="Leave for Uni",
                )
                for interval in shadowed
            ),
            forbidden_windows=(
                *(a_window(interval, ForbiddenScope.ALL) for interval in absolute_windows),
                *(
                    a_window(window.interval, ForbiddenScope.AREAS, *window.forbidden_area_ids)
                    for window in scoped_windows
                ),
            ),
            off_plan=tuple(OffPlanPeriod(interval=interval) for interval in suspended),
            areas=tuple(budgets),
            eligible_tasks=tuple(
                EligibleTask(
                    binding=task.binding,
                    remaining_minutes=task.estimate_minutes
                    - minutes_of(immovable(task.placements)),
                    priority=Priority.NORMAL,
                    min_chunk_minutes=15,
                    splittable=True,
                    area_id=task.area_id,
                    title=task.title,
                    deadline=task.deadline,
                )
                for task in tasks
            ),
            pins=tuple(one.pin for task in tasks for one in task.placements if one.pin is not None),
            deadline_demands=tuple(
                DeadlineDemand(
                    deadline=task.deadline,
                    remaining_minutes=task.estimate_minutes - minutes_of(task.placements),
                    area_id=task.area_id,
                    labels=(task.title,),
                )
                for task in tasks
            ),
            live_plan=a_document(
                *(one.block for task in tasks for one in task.placements if one.block is not None)
            ),
        ),
        areas=tuple(areas),
        tasks=tuple(tasks),
        absolute_windows=absolute_windows,
        scoped_windows=tuple(scoped_windows),
    )


def carried_forward(week: GeneratedWeek) -> dict[str, object]:
    """What every projected field must equal, restated from the assembly rather than read back.

    Four of these come from the drawn week's own intent instead of from the assembly, because the
    projection makes a choice about each and an expectation restating the choice in its own terms
    would assert only that it equals itself: the two halves of the scope split, and the pairing that
    makes ``placed`` and the reservations a reading of the placements rather than of the plan and
    the pins unioned.
    """
    assembled = week.inputs
    return {
        "span": assembled.span,
        "now": assembled.now,
        "computed_at": assembled.now,
        "input_version": assembled.input_version,
        "frame": IntervalSet(
            [*(entry.interval for entry in assembled.frame), *assembled.frame_overhang]
        ),
        "anchors": IntervalSet(anchor.interval for anchor in assembled.anchors),
        "absolute_forbidden": IntervalSet(week.absolute_windows),
        "scoped_forbidden": week.scoped_windows,
        "off_plan": IntervalSet(period.interval for period in assembled.off_plan),
        "placed": IntervalSet(placement.interval for placement in week.placements),
        "area_floor_reservations": tuple(
            FloorReservation(
                area_id=area.area_id,
                reserved_minutes=area.declared_floor_minutes
                - minutes_of(placements_in(week.tasks, area.area_id)),
                label=area.name,
            )
            for area in week.areas
        ),
        "area_targets": {area.area_id: area.target_minutes for area in week.areas},
        "deadline_demands": assembled.deadline_demands,
    }


@given(week=weeks_holding_unpinned_placements())
@settings(max_examples=PROJECTION_EXAMPLES, deadline=None)
def test_the_projection_agrees_field_by_field_on_a_week_holding_unpinned_placements(
    week: GeneratedWeek,
) -> None:
    """The four assertions the projection seam is worth, on the one state that can expose it.

    A wrong carry is only observable on a week whose live plan holds placements the solver may
    still move, so the fourth assertion is the load-bearing one: it says the difference the third
    measures is non-zero, and without it a generator that stopped emitting such a placement would
    pass everything here trivially.
    """
    projected = week.inputs.for_probe()
    placements = week.placements

    # The generator's own claims, asserted rather than reasoned about. An interval laid outside the
    # week would make a figure taken over the span disagree with one taken over the placements, and
    # a deadline ahead of a placement of its own task would break the netting the property models:
    # the demand nets the placements before the deadline, and every one of them has to be there.
    laid = IntervalSet(
        [
            *(placement.interval for placement in placements),
            *(entry.interval for entry in week.inputs.frame),
            *week.inputs.frame_overhang,
            *(anchor.interval for anchor in week.inputs.anchors),
            *(shadow.interval for shadow in week.inputs.shadow_blocks),
            *(window.interval for window in week.inputs.forbidden_windows),
            *(period.interval for period in week.inputs.off_plan),
        ]
    )
    assert laid == laid.clip(SPAN)
    assert all(SPAN.start <= task.deadline < SPAN.end for task in week.tasks)
    assert all(one.interval.end <= task.deadline for task in week.tasks for one in task.placements)

    # 1. Every projected field equals its source, and the two the assembly hands over whole are
    #    the assembly's own objects rather than equal copies of them.
    expected = carried_forward(week)
    assert set(expected) == {field.name for field in dataclasses.fields(ProbeInputs)}
    for name, value in expected.items():
        assert getattr(projected, name) == value, name
    for name in CARRIED_BY_IDENTITY:
        assert getattr(projected, name) is getattr(week.inputs, PROJECTED_FROM[name]), name

    # 2. One placement set on both sides of every comparison. Each quantity the probe compares
    #    against `free` nets its own Area's or its own task's placements, and together those are
    #    exactly the set `free` subtracts.
    by_reservation = {
        reservation.area_id: placements_in(week.tasks, reservation.area_id)
        for reservation in projected.area_floor_reservations
    }
    by_deadline = {task.deadline: task for task in week.tasks}
    assert len(by_deadline) == len(week.tasks)
    assert set(by_deadline) == {demand.deadline for demand in projected.deadline_demands}
    assert (
        IntervalSet(one.interval for netted in by_reservation.values() for one in netted)
        == projected.placed
    )
    assert (
        IntervalSet(one.interval for task in by_deadline.values() for one in task.placements)
        == projected.placed
    )

    # `free` as the probe derives it, restated here so the set the assertion above names has a
    # referent. A scoped window is in neither the denominator nor `free`: it is capacity for every
    # Area it does not name, and it bites only in the two per-Area readings.
    free = (
        discretionary_intervals(
            projected.span,
            frame=projected.frame,
            anchors=projected.anchors,
            absolute_forbidden=projected.absolute_forbidden,
            off_plan=projected.off_plan,
        )
        .after(projected.now)
        .subtract(projected.placed)
    )
    scoped = IntervalSet(window.interval for window in week.scoped_windows)
    assert free.intersect(scoped) == scoped
    for area in week.areas:
        forbidden_here = IntervalSet(
            window.interval for window in week.scoped_windows if window.forbids(area.area_id)
        )
        assert free.subtract(projected.scoped_against(area.area_id)) == free.subtract(
            forbidden_here
        )

    # 3. Each pair differs by exactly the unpinned future placements, per Area and per task. The
    #    solver's figure is the larger one because it nets the narrower set, so the difference runs
    #    this way round.
    reserved = {
        reservation.area_id: reservation.reserved_minutes
        for reservation in projected.area_floor_reservations
    }
    for budget in week.inputs.areas:
        here = placements_in(week.tasks, budget.area_id)
        assert budget.floor_minutes - reserved[budget.area_id] == minutes_of(movable(here))
    demanded = {demand.deadline: demand.remaining_minutes for demand in projected.deadline_demands}
    remaining = {task.binding: task.remaining_minutes for task in week.inputs.eligible_tasks}
    for task in week.tasks:
        difference = remaining[task.binding] - demanded[task.deadline]
        assert difference == minutes_of(movable(task.placements)), task.title

    # 4. Non-vacuity. The right-hand side above is non-zero for the week, for at least one Area and
    #    for at least one task, so no assertion here can pass by the two quantities of a pair being
    #    equal on a week that holds nothing the solver may still move.
    assert minutes_of(movable(placements)) > 0
    assert any(
        minutes_of(movable(placements_in(week.tasks, area.area_id))) > 0 for area in week.areas
    )
    assert any(minutes_of(movable(task.placements)) > 0 for task in week.tasks)
