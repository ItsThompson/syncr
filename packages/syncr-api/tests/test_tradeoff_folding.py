"""What a concession's approval modifies, observed rather than described, and in which direction.

The blocker this suite exists against: the four kinds' approval effects were written when the
solver's demand and the probe's demand were one field. After the split, three of the four touch two
quantities, and a row of prose naming one of a pair reads as complete. Each incompleteness has its
own user-visible failure, and none of them is visible in the plan document: the concession simply
appears not to have worked.

So the fold declares which ``SolveInputs`` fields each kind modifies, and this suite folds one
concession of each kind through a real assembly, observes which fields actually moved, and compares
the observation against the declaration in both directions. A field that moves and is not declared
fails here, and so does a declared field that no longer moves.

Beside that, the direction. Every kind is offered by the enumerator with a stated recovery, and for
each kind a Tier-2 test asserts the verdict moves the way the tradeoff promised: the gap it was
offered against closes by at least the minutes it claimed. That is the assertion nothing had before,
and it is the one that would have caught a breach that lowered the solver's floor and left the
probe's reservation alone.
"""

from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

from syncr_api.plans.folding import FOLDED_FIELDS, Concessions, fold
from syncr_api.plans.tradeoffs import Offer, offered_tradeoffs
from syncr_domain.feasibility import DeadlineDemand, ShortfallKind, probe
from syncr_domain.fixtures import elastic_sleep
from syncr_domain.identity import BindingRef
from syncr_domain.plan import AdjustmentKind, Block
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind
from syncr_solver.inputs import AreaBudget, EligibleTask, FrameEntry, SolveInputs, WeekAdjustment
from tests.assembly_fakes import (
    A_REASON,
    MINUTES_PER_HOUR,
    NOW,
    WEEK,
    FakeAdjustments,
    FakeAreas,
    FakeOffPlan,
    FakePlacements,
    FakePreferences,
    FakeRoutines,
    FakeTasks,
    a_plan,
    a_preference,
    a_routine,
    a_task,
    an_adjustment,
    an_area,
    an_assembler,
    an_off_plan_period,
    at,
    between,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.plans.assembler import WeekAssembler
    from syncr_domain.feasibility import Shortfall, Verdict
    from syncr_domain.identifiers import AreaId, TaskId

CAREER_TASK: TaskId = UUID("f2f2f2f2-0000-4000-8000-000000000001")
FITNESS_TASK: TaskId = UUID("f2f2f2f2-0000-4000-8000-000000000002")

# The member type each collection on `SolveInputs` holds, for the dotted half of a declared path.
# Bounded by what the fold can reach: a path naming a collection absent here is a declaration this
# suite cannot check, which fails rather than passing quietly.
MEMBER_TYPES: Mapping[str, type] = {
    "frame": FrameEntry,
    "eligible_tasks": EligibleTask,
    "areas": AreaBudget,
    "deadline_demands": DeadlineDemand,
}


def field_names(shape: type) -> set[str]:
    return {one.name for one in fields(shape)}


def moved_fields(before: SolveInputs, after: SolveInputs) -> set[str]:
    """Every field of ``SolveInputs`` that differs, dotted where one member's value changed.

    A collection whose membership changed is named by the collection: dropping a task is a change to
    ``eligible_tasks`` itself. A collection whose members are the same in number and order but hold
    a different value is named by that member field, so lowering a floor reads as
    ``areas.floor_minutes`` rather than as "areas changed".
    """
    moved: set[str] = set()
    for one in fields(before):
        held, now = getattr(before, one.name), getattr(after, one.name)
        if held == now:
            continue
        if isinstance(held, tuple) and isinstance(now, tuple) and len(held) == len(now):
            moved |= _member_fields(one.name, held, now)
            continue
        moved.add(one.name)
    return moved


def _member_fields(collection: str, before: Sequence[Any], after: Sequence[Any]) -> set[str]:
    """Which member field differs, pairwise, or the collection itself when the members swapped."""
    moved: set[str] = set()
    for held, now in zip(before, after, strict=True):
        if held == now:
            continue
        differing = {
            one.name
            for one in fields(held)
            if getattr(held, one.name) != getattr(now, one.name, None)
        }
        moved |= {f"{collection}.{name}" for name in differing} or {collection}
    return moved


def a_week_every_kind_can_be_offered_in() -> WeekAssembler:
    """One assembly a concession of any of the four kinds applies to.

    Forty hours of Career work due Thursday morning, a Fitness floor with nowhere after it to fit,
    an elastic sleep routine with two reducible nights before the deadline, and a preference on the
    task so the field the prose tables do not name is observable.
    """
    career = an_area(name="Career")
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=40 * MINUTES_PER_HOUR,
        deadline=at(10, day=3),
    )
    return an_assembler(
        areas=FakeAreas([fitness, career]),
        tasks=FakeTasks([task]),
        routines=FakeRoutines([_elastic_sleep()]),
        preferences=FakePreferences([a_preference(owner=_a_task_owner(task.id))]),
        off_plan=FakeOffPlan([an_off_plan_period(interval=between(10, 24 * 4 + 24, day=3))]),
    )


def _a_task_owner(task_id: TaskId) -> PreferenceOwner:
    """A preference attached to one task. The shared builders name an Area and a Habit only."""
    return PreferenceOwner(kind=PreferenceOwnerKind.TASK, id=task_id)


def _elastic_sleep() -> Any:
    return a_routine(
        title=elastic_sleep.TITLE,
        target_time=elastic_sleep.TARGET_TIME,
        duration_minutes=elastic_sleep.DURATION_MINUTES,
        min_duration_minutes=elastic_sleep.MIN_DURATION_MINUTES,
    )


async def an_offered(kind: AdjustmentKind) -> tuple[WeekAssembler, SolveInputs, Offer]:
    """The assembler, its unfolded inputs, and the offer of ``kind`` the enumerator made for it."""
    assembler = a_week_every_kind_can_be_offered_in()
    inputs = await assembler.assemble(WEEK, elastic_sleep.NOW)
    offers = offered_tradeoffs(inputs, probe(inputs.for_probe()))
    offer = next(one for one in offers if one.tradeoff.kind is kind)
    return assembler, inputs, offer


def gap_of(verdict: Verdict, kind: ShortfallKind) -> Shortfall | None:
    return next((one for one in verdict.shortfalls if one.kind is kind), None)


def minutes_of(verdict: Verdict, kind: ShortfallKind) -> int:
    """How short the week is by one measure, or zero when that measure found nothing."""
    gap = gap_of(verdict, kind)
    return 0 if gap is None else gap.minutes


# --------------------------------------------------------------------------------
# The declared mapping, against what actually moves
# --------------------------------------------------------------------------------


def test_every_kind_of_concession_declares_the_fields_its_approval_modifies() -> None:
    # Bounded by the vocabulary rather than by a list maintained here, so a fifth kind cannot arrive
    # with no declaration at all.
    assert set(FOLDED_FIELDS) == set(AdjustmentKind)
    assert all(FOLDED_FIELDS[kind] for kind in AdjustmentKind)


def test_every_declared_field_is_a_field_the_resolved_inputs_actually_hold() -> None:
    # The declaration is only a check if each name resolves. A renamed field on `SolveInputs`, or on
    # one of the collections' member types, fails here rather than leaving a row that points at
    # nothing.
    for named in sorted(set().union(*FOLDED_FIELDS.values())):
        collection, _, member = named.partition(".")
        assert collection in field_names(SolveInputs), named
        if member:
            assert collection in MEMBER_TYPES, named
            assert member in field_names(MEMBER_TYPES[collection]), named


@pytest.mark.parametrize("kind", list(AdjustmentKind))
async def test_approving_one_concession_moves_exactly_the_fields_it_declares(
    kind: AdjustmentKind,
) -> None:
    # The whole of B2, asserted by observation. Every field of the resolved inputs is compared, so a
    # kind that touches one of a pair fails, and so does one that reaches a field nobody declared.
    assembler, before, offer = await an_offered(kind)

    after = await assembler.assemble(
        WEEK, elastic_sleep.NOW, offer.as_candidate(adjustment_id=uuid4())
    )

    # The concession list itself always moves: the assembly carries what it was solved under, so a
    # reason clause can cite it. That is not a field the concession's own effect modifies.
    assert moved_fields(before, after) - {"adjustments"} == FOLDED_FIELDS[kind]


async def test_a_dropped_task_takes_its_resolved_preference_with_it() -> None:
    # The field neither prose table names. Preferences are resolved over the FOLDED eligibility, so
    # dropping a task removes its window too, which is right: a task nothing will schedule this week
    # needs no window. It is declared for that reason rather than discovered by a reader.
    assembler, before, offer = await an_offered(AdjustmentKind.DROP_ITEM)

    after = await assembler.assemble(
        WEEK, elastic_sleep.NOW, offer.as_candidate(adjustment_id=uuid4())
    )

    assert [one.owner.id for one in before.preferences] == [CAREER_TASK]
    assert after.preferences == ()
    assert "preferences" in FOLDED_FIELDS[AdjustmentKind.DROP_ITEM]


async def test_a_dropped_task_keeps_its_status_because_that_is_a_different_act() -> None:
    # Dropping a task permanently means something else. The concession is about one week, so the
    # backlog row is untouched and the task returns next week without being reinstated.
    task = a_task(task_id=CAREER_TASK, area_id=an_area().id, estimate_minutes=60)
    tasks = FakeTasks([task])
    assembler = an_assembler(
        tasks=tasks,
        adjustments=FakeAdjustments(
            [an_adjustment(kind=AdjustmentKind.DROP_ITEM.value, target_id=task.id)]
        ),
    )

    inputs = await assembler.assemble(WEEK, NOW)

    assert inputs.eligible_tasks == ()
    assert [row.status for row in await tasks.list_all()] == [task.status]


# --------------------------------------------------------------------------------
# The direction each tradeoff promised
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(AdjustmentKind))
async def test_approving_a_tradeoff_closes_the_deadline_gap_when_no_floor_fits_later(
    kind: AdjustmentKind,
) -> None:
    # The observation review 5 asked for, over the ONE week shape where it holds for all four kinds:
    # nothing after the deadline can absorb a floor, so the whole reservation is charged before it
    # and a breach lowers the competition by the whole of what it concedes. That condition is in the
    # name because it is load-bearing rather than incidental: relax it and the breach figure becomes
    # an upper bound, which `test_a_breach_can_state_more_than_a_deadline_gap_can_fall_by` draws.
    #
    # The gap is asserted to be the only one of its kind, so the measurement cannot silently take a
    # different deadline's shortfall than the one these offers were computed against.
    assembler, before, offer = await an_offered(kind)
    held = probe(before.for_probe())

    after = await assembler.assemble(
        WEEK, elastic_sleep.NOW, offer.as_candidate(adjustment_id=uuid4())
    )

    deadline_gaps = [one for one in held.shortfalls if one.kind is ShortfallKind.DEADLINE_CAPACITY]
    assert len(deadline_gaps) == 1
    assert offer.recovers > 0
    left = minutes_of(probe(after.for_probe()), ShortfallKind.DEADLINE_CAPACITY)
    assert deadline_gaps[0].minutes - left >= offer.recovers


async def test_a_breach_can_state_more_than_a_deadline_gap_can_fall_by() -> None:
    # The bound the enumerator's docstring states, drawn rather than described, on a week reachable
    # through the shipped routes: two Areas, one 7h floor, two ordinary tasks an hour apart, one
    # off-plan declaration that leaves capacity AFTER the later deadline.
    #
    # The deadline check subtracts `max(claimed, reserved - absorbed_later)` rather than the
    # reservation, so a floor that partly fits after the deadline is charged for part of itself and
    # a breach of the whole reservation cannot lower the competition by the whole of it. `_breaches`
    # caps at the reservation, which is blind to that split.
    #
    # The figure is therefore an UPPER bound on the gap movement, which is the safe direction for a
    # panel to be wrong in only because the alternative is worse: a row promising less than it
    # delivers would have the user approve two concessions where one sufficed. Closing it needs a
    # per-floor contribution carried on the shortfall, which is one decision with 1361's.
    fitness = an_area(name="Fitness", floor_hours=Decimal(7))
    career = an_area(name="Career")
    assembler = an_assembler(
        areas=FakeAreas([fitness, career]),
        tasks=FakeTasks(
            [
                a_task(
                    task_id=FITNESS_TASK,
                    area_id=fitness.id,
                    title="Gym block",
                    estimate_minutes=300,
                    deadline=at(12, day=2),
                ),
                a_task(
                    task_id=CAREER_TASK,
                    area_id=career.id,
                    title="F&F Past Papers",
                    estimate_minutes=300,
                    deadline=at(13, day=2),
                ),
            ]
        ),
        off_plan=FakeOffPlan([an_off_plan_period(interval=between(18, 24 * 4 + 24, day=2))]),
    )
    before = await assembler.assemble(WEEK, at(9, day=2))
    held = probe(before.for_probe())
    breach = next(
        one
        for one in offered_tradeoffs(before, held)
        if one.tradeoff.kind is AdjustmentKind.BREACH_FLOOR and one.tradeoff.target_id == fitness.id
    )

    after = await assembler.assemble(WEEK, at(9, day=2), breach.as_candidate(adjustment_id=uuid4()))

    # Every gap's movement, so the claim is about the whole verdict rather than one measure.
    left = probe(after.for_probe())
    moved = {key: _minutes(held, key) - _minutes(left, key) for key in {*_keys(held), *_keys(left)}}
    assert before.areas[0].floor_reservation_minutes == 420
    assert breach.recovers == 240
    assert breach.tradeoff.label == "Breach the Fitness floor by 4h"
    # The largest movement anywhere in the verdict is 180, and the deadline gaps do not move at all.
    assert max(moved.values()) == 180
    assert max(moved.values()) < breach.recovers
    assert moved[(ShortfallKind.DEADLINE_CAPACITY, career.id)] == 0
    # And the fold still did both halves of its job, which is what makes this the FIGURE's fault.
    assert after.areas[0].floor_minutes == 420 - 240
    assert after.areas[0].floor_reservation_minutes == 420 - 240


def _keys(verdict: Verdict) -> set[tuple[ShortfallKind, AreaId | None]]:
    return {(one.kind, one.area_id) for one in verdict.shortfalls}


def _minutes(verdict: Verdict, key: tuple[ShortfallKind, AreaId | None]) -> int:
    """One gap's size, keyed by kind and Area, or zero where the verdict holds no such gap."""
    return next(
        (one.minutes for one in verdict.shortfalls if (one.kind, one.area_id) == key),
        0,
    )


async def test_breaching_a_floor_closes_the_floors_gap_the_probe_reports() -> None:
    # Blocker 1's field pair, end to end. The user clicks "Breach the Fitness floor", approves, and
    # the verdict panel must stop reporting the same gap: the probe reads the reservation and H9
    # reads the floor, so a breach that lowered one and not the other would change no reading the
    # user can see.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career", floor_hours=Decimal(3))
    tight = FakeOffPlan([an_off_plan_period(interval=between(15, 24 * 4 + 24, day=2))])
    assembler = an_assembler(areas=FakeAreas([fitness, career]), off_plan=tight)
    before = await assembler.assemble(WEEK, NOW)
    offer = next(
        one
        for one in offered_tradeoffs(before, probe(before.for_probe()))
        if one.tradeoff.kind is AdjustmentKind.BREACH_FLOOR
    )

    after = await assembler.assemble(WEEK, NOW, offer.as_candidate(adjustment_id=uuid4()))

    assert minutes_of(probe(before.for_probe()), ShortfallKind.FLOORS_EXCEED_CAPACITY) == 120
    assert offer.recovers == 120
    assert gap_of(probe(after.for_probe()), ShortfallKind.FLOORS_EXCEED_CAPACITY) is None
    assert after.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR - 120
    assert after.areas[0].floor_reservation_minutes == 5 * MINUTES_PER_HOUR - 120


async def test_reducing_a_routine_closes_the_gap_the_nights_were_chosen_for() -> None:
    # The elastic_sleep fixture end to end: sixty minutes short, twenty minutes of give a night,
    # three nights named, and the gap gone afterwards.
    fitness = an_area(name="Fitness", floor_hours=Decimal(95))
    assembler = an_assembler(areas=FakeAreas([fitness]), routines=FakeRoutines([_elastic_sleep()]))
    before = await assembler.assemble(WEEK, elastic_sleep.NOW)
    offer = next(
        one
        for one in offered_tradeoffs(before, probe(before.for_probe()))
        if one.tradeoff.kind is AdjustmentKind.REDUCE_ROUTINE
    )

    after = await assembler.assemble(
        WEEK, elastic_sleep.NOW, offer.as_candidate(adjustment_id=uuid4())
    )

    assert offer.reductions == elastic_sleep.REDUCTIONS
    assert minutes_of(probe(before.for_probe()), ShortfallKind.FLOORS_EXCEED_CAPACITY) == 60
    assert gap_of(probe(after.for_probe()), ShortfallKind.FLOORS_EXCEED_CAPACITY) is None


# --------------------------------------------------------------------------------
# The invariants the concession table carries
# --------------------------------------------------------------------------------


async def test_a_candidate_and_a_stored_concession_of_one_kind_resolve_to_one_assembly() -> None:
    # WA2's other half: requesting persists nothing, so the candidate path and the stored path have
    # to produce the same inputs or a request would be evaluated against a week approval will not
    # reproduce. Identical apart from the concession's own identity, which storage mints.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    stored = an_adjustment(
        kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=120
    )
    candidate = WeekAdjustment(
        adjustment_id=stored.id,
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=fitness.id,
        delta_minutes=120,
    )

    persisted = await an_assembler(
        areas=FakeAreas([fitness]), adjustments=FakeAdjustments([stored])
    ).assemble(WEEK, NOW)
    evaluated = await an_assembler(areas=FakeAreas([fitness])).assemble(WEEK, NOW, candidate)

    assert persisted == evaluated


async def test_several_concessions_in_one_week_compose_because_each_names_a_distinct_target() -> (
    None
):
    # WA3. Three kinds against three targets in one week, each applying in full: the fold is one
    # pass over one list, so composition is what it does rather than a case it handles.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career")
    task = a_task(
        task_id=CAREER_TASK, area_id=career.id, estimate_minutes=120, deadline=at(10, day=4)
    )
    sleep = _elastic_sleep()

    inputs = await an_assembler(
        areas=FakeAreas([fitness, career]),
        tasks=FakeTasks([task]),
        routines=FakeRoutines([sleep]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=60
                ),
                an_adjustment(kind=AdjustmentKind.DROP_ITEM.value, target_id=task.id),
                an_adjustment(
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=sleep.id,
                    reductions={elastic_sleep.WEDNESDAY.isoformat(): 20},
                ),
            ]
        ),
    ).assemble(WEEK, NOW)

    wednesday = next(
        entry
        for entry in inputs.frame
        if entry.occurrence_key == elastic_sleep.WEDNESDAY.isoformat()
    )
    assert inputs.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR - 60
    assert inputs.eligible_tasks == ()
    assert wednesday.interval.total_minutes() == elastic_sleep.DURATION_MINUTES - 20
    assert len(inputs.adjustments) == 3


async def test_a_concession_approved_for_another_week_reaches_none_of_this_weeks_figures() -> None:
    # WA1: week-scoped and never carried forward, for the same reason a pin is not. A hard week must
    # not silently become the new normal.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    elsewhere = replace(
        an_adjustment(
            kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=120
        ),
        iso_week=WEEK.following(),
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), adjustments=FakeAdjustments([elsewhere])
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR
    assert inputs.adjustments == ()


# --------------------------------------------------------------------------------
# The fold at its edges
# --------------------------------------------------------------------------------


async def test_folding_no_concessions_leaves_every_resolved_figure_alone() -> None:
    # The ordinary week, and the pass's identity: a week nobody conceded anything for reads exactly
    # as its declarations say.
    inputs = await a_week_every_kind_can_be_offered_in().assemble(WEEK, elastic_sleep.NOW)
    resolved = Concessions(
        frame=inputs.frame,
        eligible_tasks=inputs.eligible_tasks,
        demands=(),
        areas=inputs.areas,
    )

    assert fold((), resolved) == resolved


async def test_folding_one_concession_twice_applies_it_twice() -> None:
    # The measured behaviour, and it is what an increment means: each concession lowers the figure
    # as it stands. What makes it unreachable is the input rather than a guard here: the assembler
    # builds the list from one read of a table unique per kind and target, plus at most one
    # candidate, and the candidate's identity is minted per request.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    inputs = await an_assembler(areas=FakeAreas([fitness])).assemble(WEEK, NOW)
    breach = WeekAdjustment(
        adjustment_id=uuid4(),
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=fitness.id,
        delta_minutes=60,
    )
    resolved = Concessions(
        frame=inputs.frame, eligible_tasks=inputs.eligible_tasks, demands=(), areas=inputs.areas
    )

    once = fold((breach,), resolved)
    twice = fold((breach, breach), resolved)

    assert once.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR - 60
    assert twice.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR - 120


async def test_a_breach_of_no_minutes_lowers_nothing() -> None:
    # Zero beside the negative figure already measured: neither lowers a floor, and for the same
    # reason. A concession that concedes nothing must not read as one that did.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=0
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR
    assert inputs.areas[0].floor_reservation_minutes == 5 * MINUTES_PER_HOUR


async def test_dropping_and_excusing_one_task_compose_to_one_answer_in_either_order() -> None:
    # Two kinds against one target, which the storage index allows because it is keyed by both.
    # The work leaves either way, so the order cannot matter: dropping removes the task eligibility
    # carries the excused deadline on, and excusing a task nothing will schedule changes nothing.
    career = an_area(name="Career")
    task = a_task(
        task_id=CAREER_TASK, area_id=career.id, estimate_minutes=120, deadline=at(10, day=4)
    )
    dropped = an_adjustment(kind=AdjustmentKind.DROP_ITEM.value, target_id=task.id)
    excused = an_adjustment(kind=AdjustmentKind.ACCEPT_PARTIAL.value, target_id=task.id)

    forward = await an_assembler(
        areas=FakeAreas([career]),
        tasks=FakeTasks([task]),
        adjustments=FakeAdjustments([dropped, excused]),
    ).assemble(WEEK, NOW)
    backward = await an_assembler(
        areas=FakeAreas([career]),
        tasks=FakeTasks([task]),
        adjustments=FakeAdjustments([excused, dropped]),
    ).assemble(WEEK, NOW)

    assert forward.eligible_tasks == ()
    assert forward.deadline_demands == ()
    assert forward.eligible_tasks == backward.eligible_tasks
    assert forward.deadline_demands == backward.deadline_demands


async def test_a_reduction_frees_nothing_the_live_plan_still_commits_that_night_to() -> None:
    # A measurement rather than a rule, recorded because the direction is not obvious and the figure
    # is what a reader would otherwise assume.
    #
    # The frame arrives shortened by the fold, so the week's occupancy releases the twenty minutes.
    # The live plan still holds THAT NIGHT'S BLOCK at its declared length, and free capacity
    # subtracts every placement, so the released span stays committed until the solve this
    # request asks for re-places it. The concession's stated recovery is the minutes it hands
    # back to the week, which is true; the gap moves when the plan catches up.
    #
    # This is not the double-subtraction shape: one set is subtracted once by each of two
    # quantities that answer different questions. `placed` is what the week has committed and the
    # frame is what it reserves, and the pair is what the next solve reconciles. A frame block
    # carries no Area, by the document's own rule, so no Area figure is involved either way.
    fitness = an_area(name="Fitness", floor_hours=Decimal(95))
    sleep = _elastic_sleep()
    tuesday = elastic_sleep.TUESDAY
    committed = FakePlacements(
        live_plan=a_plan(
            blocks=[
                Block(
                    iso_week=WEEK,
                    interval=elastic_sleep.TUESDAY_NIGHT,
                    binding=BindingRef.for_routine(sleep.id, on=tuesday),
                    title=elastic_sleep.TITLE,
                    reason=A_REASON,
                )
            ]
        )
    )
    assembler = an_assembler(
        areas=FakeAreas([fitness]), routines=FakeRoutines([sleep]), placements=committed
    )
    before = await assembler.assemble(WEEK, elastic_sleep.NOW)
    offer = next(
        one
        for one in offered_tradeoffs(before, probe(before.for_probe()))
        if one.tradeoff.kind is AdjustmentKind.REDUCE_ROUTINE
    )

    after = await assembler.assemble(
        WEEK, elastic_sleep.NOW, offer.as_candidate(adjustment_id=uuid4())
    )

    # The frame really is shorter, and the whole-week denominator really does grow by the reduction.
    tuesday_night = next(
        entry for entry in after.frame if entry.occurrence_key == tuesday.isoformat()
    )
    assert tuesday_night.interval.total_minutes() == elastic_sleep.DURATION_MINUTES - 20
    assert (
        probe(after.for_probe()).discretionary_minutes
        - probe(before.for_probe()).discretionary_minutes
        == offer.recovers
    )
    # And the gap falls by the two nights the plan does NOT hold a block for, not by all three: the
    # Tuesday block still commits its own twenty minutes.
    held = minutes_of(probe(before.for_probe()), ShortfallKind.FLOORS_EXCEED_CAPACITY)
    left = minutes_of(probe(after.for_probe()), ShortfallKind.FLOORS_EXCEED_CAPACITY)
    assert held - left == offer.recovers - 20
