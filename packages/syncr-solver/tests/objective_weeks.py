"""Builders for the inputs the seven objective terms read, on top of the materialization ones.

The objective takes a whole week plus a whole plan, so a test asserting one term would otherwise
spell six terms' worth of values it does not care about. These produce a week in which every term
is ZERO by default, so a test states only what it drives and any cost it measures is the cost of
what it stated.

Every value is real: the interval algebra, the identity derivation, the domain value types, and
the hand-tuned weights are the shipped ones. ``hand_tuned_weights`` is built from the api's own
``P0_WEIGHTS`` rather than from a copy of the numbers, so the fixture is version 1's weights and
not a second statement of them; that is also the crossing that catches the two vocabularies
drifting, and it is why this suite needs the api member importable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from syncr_api.learned.config import P0_WEIGHTS
from syncr_domain.habits import BindingSource, Duration
from syncr_domain.identity import BindingRef
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind, PreferenceStrength
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.tasks import Priority
from syncr_solver.inputs import (
    AreaBudget,
    ChurnBaseline,
    EligibleTask,
    HabitOccurrence,
    ResolvedPreference,
)
from syncr_solver.objective import ObjectiveBreakdown
from syncr_solver.terms import StalenessSplit
from syncr_solver.weights import OBJECTIVE_TERMS, TimeBucket, WeightSet
from tests.materialized_weeks import CAREER, FITNESS, LONDON, NOW, WEEK, WEEK_MINUTES, between

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneId

# Eleven hours ahead of UTC in February, so a block at 10:00 UTC reads at 21:00 locally and falls in
# a different time bucket. What a test about the zone an hour is read in needs.
SYDNEY = "Australia/Sydney"

A_TASK: UUID = UUID("00000000-0000-4000-8000-0000000000a1")
ANOTHER_TASK: UUID = UUID("00000000-0000-4000-8000-0000000000a2")
A_HABIT: UUID = UUID("00000000-0000-4000-8000-0000000000b1")
ANOTHER_HABIT: UUID = UUID("00000000-0000-4000-8000-0000000000b2")

# The revision a baseline names, and the instant of assent. Neither is read by any arithmetic: a
# baseline needs both before it can name a plan, and this is what it names.
A_REVISION: UUID = UUID("00000000-0000-4000-8000-0000000000c1")
A_MOMENT = NOW


def hand_tuned_weights(**overrides: Any) -> WeightSet:
    """Weight set version 1: the P0 numbers, hand-tuned, as the solve path reads them.

    The fitted maps are empty, which is what "nothing has been learned yet" looks like: a
    parameter below its maturity gate is not applied at all, and absence is how that is stated.
    """
    stated: dict[str, Any] = dict(P0_WEIGHTS)
    stated.update(overrides)
    return WeightSet(**stated)


def flat_weights(**overrides: Any) -> WeightSet:
    """Every term weighted at one, so a breakdown reads as the raw measurements themselves.

    What a test of one term's ARITHMETIC uses. A test of how the terms trade off against each
    other uses ``hand_tuned_weights``, because that is the question the weights answer.
    """
    stated: dict[str, Any] = dict.fromkeys(P0_WEIGHTS, 1.0)
    stated["churn_tolerance"] = 1.0
    stated.update(overrides)
    return WeightSet(**stated)


def an_eligible_task(
    *,
    task_id: UUID | None = None,
    remaining_minutes: int = 60,
    deadline: Any = None,
    min_chunk_minutes: int = 15,
    splittable: bool = True,
    area_id: AreaId = FITNESS,
    title: str = "Leetcode",
    priority: Priority = Priority.NORMAL,
) -> EligibleTask:
    """One open task the solver may place, with the SOLVER's remaining-minutes quantity."""
    return EligibleTask(
        binding=BindingRef.for_task(task_id or A_TASK),
        remaining_minutes=remaining_minutes,
        priority=priority,
        min_chunk_minutes=min_chunk_minutes,
        splittable=splittable,
        area_id=area_id,
        title=title,
        deadline=deadline,
    )


def an_occurrence(
    *,
    habit_id: UUID | None = None,
    index: int = 0,
    minutes: int = 60,
    max_minutes: int | None = None,
    variant: str | None = None,
    is_debt: bool = False,
    area_id: AreaId = FITNESS,
    title: str = "Gym",
) -> HabitOccurrence:
    """One due occurrence of one habit. A variant means its content came from the rotation."""
    return HabitOccurrence(
        binding=BindingRef.for_habit(habit_id or A_HABIT, index=index),
        duration=Duration(min_minutes=minutes, max_minutes=max_minutes or minutes),
        area_id=area_id,
        title=title,
        variant=variant,
        is_debt=is_debt,
    )


def a_preference(
    *,
    owner_id: UUID | None = None,
    kind: PreferenceOwnerKind = PreferenceOwnerKind.AREA,
    windows: tuple[Interval, ...] = (),
    strength: PreferenceStrength = PreferenceStrength.SOFT,
    preferred_duration_minutes: int | None = None,
) -> ResolvedPreference:
    """One owner's preference, already resolved down the override chain for this week."""
    return ResolvedPreference(
        owner=PreferenceOwner(kind=kind, id=owner_id or FITNESS),
        windows=windows,
        strength=strength,
        preferred_duration_minutes=preferred_duration_minutes,
    )


def a_window(start_hour: float, end_hour: float, *, day: int = 0) -> Interval:
    """One preferred window, resolved to instants for one date of this week."""
    return between(start_hour, end_hour, day=day)


def a_fitness_curve(*, at_hour: int, value: float, elsewhere: float = 1.0) -> tuple[float, ...]:
    """A fitted time-of-day curve that differs from ideal at exactly one hour."""
    return tuple(value if hour == at_hour else elsewhere for hour in range(24))


def skip_probabilities(
    *, area_id: AreaId = FITNESS, bucket: TimeBucket = TimeBucket.MORNING, value: float = 1.0
) -> dict[tuple[AreaId, TimeBucket], float]:
    """One fitted skip probability, for one Area in one part of the day."""
    return {(area_id, bucket): value}


def a_budget(
    *,
    area_id: AreaId = FITNESS,
    target_minutes: int = 0,
    floor_minutes: int = 0,
    placed_minutes: int = 0,
    name: str = "Fitness",
) -> AreaBudget:
    """One Area's figures, with ``placed_minutes`` statable.

    Separate from the materialization suite's builder because that one holds ``placed_minutes`` at
    zero, and the objective needs a week where the figure is non-zero to prove no term adds it to
    the plan's own blocks.
    """
    return AreaBudget(
        area_id=area_id,
        name=name,
        floor_minutes=floor_minutes,
        floor_reservation_minutes=floor_minutes,
        target_minutes=target_minutes,
        placed_minutes=placed_minutes,
    )


def a_plan_for(iso_week: IsoWeek) -> PlanDocument:
    """An empty document of another week, for the guard that refuses to pair across weeks."""
    return PlanDocument(
        iso_week=iso_week,
        zone_by_date=dict.fromkeys(iso_week.dates(), LONDON),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
    )


def a_chunk_block(
    *,
    task_id: UUID | None = None,
    index: int = 0,
    of: int = 2,
    interval: Interval | None = None,
    area_id: AreaId = FITNESS,
    title: str = "Leetcode",
) -> Block:
    """One chunk of a divided task, which is what two blocks of one task have to be.

    A document refuses two blocks sharing an identity, and a task's blocks are keyed by their chunk
    index, so a split task's pieces carry an index and the count they are one of.
    """
    return Block(
        iso_week=WEEK,
        interval=interval or between(10, 11),
        binding=BindingRef.for_task(task_id or A_TASK, split_index=index),
        title=title,
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected=title),)),
        area_id=area_id,
        split_count=of,
    )


def a_breakdown(**costs: float) -> ObjectiveBreakdown:
    """A breakdown from costs alone, for the arithmetic over the seven of them.

    It supplies the split and the baseline whenever a cost needs one, because the two cross-field
    guards have their own tests and those build the value through :func:`raw_breakdown` instead.
    """
    unknown = set(costs) - set(OBJECTIVE_TERMS)
    if unknown:
        raise AssertionError(f"not objective terms: {sorted(unknown)}")
    stated = {name: costs.get(name, 0.0) for name in OBJECTIVE_TERMS}
    return ObjectiveBreakdown(
        deadline_risk=stated["deadline_risk"],
        budget_deviation=stated["budget_deviation"],
        time_of_day_misfit=stated["time_of_day_misfit"],
        fragmentation=stated["fragmentation"],
        churn=stated["churn"],
        context_switch=stated["context_switch"],
        staleness=stated["staleness"],
        staleness_split=(
            StalenessSplit(cadence_minutes=1, due_minutes=1)
            if stated["staleness"]
            else StalenessSplit()
        ),
        churn_baseline=(
            ChurnBaseline.approved(A_REVISION, A_MOMENT, a_plan_for(WEEK))
            if stated["churn"]
            else ChurnBaseline.never_approved()
        ),
    )


def raw_breakdown(**costs: float) -> ObjectiveBreakdown:
    """A breakdown from costs alone, supplying NOTHING the cross-field guards want.

    What the guard tests build, so a charged churn or staleness reaches the refusal rather than a
    fixture that quietly satisfied it.
    """
    stated = {name: costs.get(name, 0.0) for name in OBJECTIVE_TERMS}
    return ObjectiveBreakdown(
        deadline_risk=stated["deadline_risk"],
        budget_deviation=stated["budget_deviation"],
        time_of_day_misfit=stated["time_of_day_misfit"],
        fragmentation=stated["fragmentation"],
        churn=stated["churn"],
        context_switch=stated["context_switch"],
        staleness=stated["staleness"],
    )


def a_plan_in(zone: ZoneId, *blocks: Block) -> PlanDocument:
    """The week's plan, with a stated zone per day.

    Separate from the materialization suite's builder because that one is Europe/London, which is
    on GMT in February, so a local wall time and its UTC spelling coincide there. A test about the
    zone an hour is read in cannot be written against a week where the two are the same.
    """
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), zone),
        discretionary_minutes=WEEK_MINUTES,
        unallocated_minutes=WEEK_MINUTES,
        oversubscription_minutes=0,
        blocks=blocks,
    )


def another_area() -> AreaId:
    """A second Area, so a test about two Areas does not have to know which identifiers exist."""
    return CAREER


def a_task_id() -> UUID:
    """A fresh task identity, for a test that needs one the fixtures do not name."""
    return uuid4()
