"""Tradeoff enumeration over a real assembly: what is offered, what it recovers, and what is not.

The enumerator is pure, and every test here still drives it over a real assembly and a real probe
verdict. That is deliberate: the applicability rules are claims about the arithmetic the probe
performed, so a test over a hand-written verdict could assert an offer against a gap the probe
would never have raised that way. The one hand-built verdict is the packing failure, which capacity
arithmetic structurally cannot produce.

Four subjects:

*Applicability.* Each kind is offered where approving it would move the figure the check compared,
and nowhere else. The breach of a floor a deadline gap did NOT honor is the case worth having: that
floor has room after the deadline, so breaching it recovers nothing and offering it would be a
button that does nothing.

*The figures.* Every offer states what it recovers, and the recovery is bounded by what the target
actually holds: a floor that reserves nothing has nothing to breach, and a routine at its own
minimum has nothing to give.

*The distribution.* A routine reduction names its nights, spread over the fewest that can supply
the gap, and never a night the week has already spent.

*What it is not.* Nothing is selected, nothing is written, and two enumerations of one assembly are
equal.
"""

from __future__ import annotations

import io
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from syncr_api.plans.tradeoffs import Offer, offered_tradeoffs
from syncr_common.logging import configure_logging
from syncr_domain.feasibility import (
    Provenance,
    ShortfallKind,
    Tradeoff,
    Verdict,
    minimum_chunk_shortfall,
    probe,
)
from syncr_domain.fixtures import elastic_sleep
from syncr_domain.identity import BindingRef
from syncr_domain.plan import AdjustmentKind
from syncr_solver.inputs import WeekAdjustment
from tests.assembly_fakes import (
    MINUTES_PER_HOUR,
    NOW,
    WEEK,
    FakeAdjustments,
    FakeAreas,
    FakeOffPlan,
    FakePlacements,
    FakeRoutines,
    FakeTasks,
    a_pin,
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
    from collections.abc import Iterator, Sequence

    from syncr_api.areas.records import AreaRecord
    from syncr_api.routines.records import RoutineRecord
    from syncr_domain.identifiers import TaskId
    from syncr_solver.inputs import SolveInputs

CAREER_TASK: TaskId = UUID("f1f1f1f1-0000-4000-8000-000000000011")
OTHER_TASK: TaskId = UUID("f1f1f1f1-0000-4000-8000-000000000012")

# Wednesday 10:00, one hour after the stamped instant, with everything from then to the end of the
# week declared off. So the capacity before the deadline is exactly one hour and the Fitness floor
# has nowhere later to fit, which is what makes it a constraint the gap honors.
DEADLINE = at(10, day=2)
REST_OF_THE_WEEK = (10, 24 * 5 + 24)


async def an_assembly(*, now: object = NOW, **overrides: object) -> SolveInputs:
    return await an_assembler(**overrides).assemble(WEEK, now)  # type: ignore[arg-type]


def offers_over(inputs: SolveInputs) -> tuple[Offer, ...]:
    """Every tradeoff offered for the week ``inputs`` describes, over its own probe verdict."""
    return offered_tradeoffs(inputs, probe(inputs.for_probe()))


def by_kind(offers: Sequence[Offer], kind: AdjustmentKind) -> list[Offer]:
    return [offer for offer in offers if offer.tradeoff.kind is kind]


def labels_of(offers: Sequence[Offer]) -> list[str]:
    return [offer.tradeoff.label for offer in offers]


def elastic_sleep_routine(*, min_duration_minutes: int | None = None) -> RoutineRecord:
    """The fixture's sleep declaration, as a stored routine row."""
    return a_routine(
        title=elastic_sleep.TITLE,
        target_time=elastic_sleep.TARGET_TIME,
        duration_minutes=elastic_sleep.DURATION_MINUTES,
        min_duration_minutes=(
            elastic_sleep.MIN_DURATION_MINUTES
            if min_duration_minutes is None
            else min_duration_minutes
        ),
    )


def a_week_the_floors_do_not_fit_in() -> tuple[AreaRecord, AreaRecord]:
    """Two Areas whose floors together need more than the week has left.

    Ten hours of capacity from Wednesday 09:00, against a five-hour and a three-hour floor plus a
    third Area with none: the floors need eight and the week holds ten, so the pair fits. Shrinking
    capacity is what makes them not.
    """
    return an_area(name="Fitness", floor_hours=Decimal(5)), an_area(
        name="Career", floor_hours=Decimal(3)
    )


# --------------------------------------------------------------------------------
# Every floor against the week
# --------------------------------------------------------------------------------


async def test_a_floors_gap_offers_a_breach_of_every_reserving_areas_floor() -> None:
    # Six hours of capacity left against an eight-hour pair of floors, so the gap is two hours and
    # either floor could give it up. Both are offered, because syncr does not choose.
    fitness, career = a_week_the_floors_do_not_fit_in()
    tight = FakeOffPlan([an_off_plan_period(interval=between(15, 24 * 4 + 24, day=2))])

    inputs = await an_assembly(areas=FakeAreas([fitness, career]), off_plan=tight)
    offers = offers_over(inputs)

    gap = probe(inputs.for_probe()).shortfalls[0]
    assert gap.kind is ShortfallKind.FLOORS_EXCEED_CAPACITY
    assert gap.minutes == 2 * MINUTES_PER_HOUR
    assert labels_of(by_kind(offers, AdjustmentKind.BREACH_FLOOR)) == [
        "Breach the Fitness floor by 2h",
        "Breach the Career floor by 2h",
    ]
    assert [offer.tradeoff.target_id for offer in by_kind(offers, AdjustmentKind.BREACH_FLOOR)] == [
        fitness.id,
        career.id,
    ]


async def test_a_breach_is_never_offered_for_more_than_the_floor_still_reserves() -> None:
    # A one-hour floor cannot give up two hours, so the offer states the hour it has. The user reads
    # a figure below the gap and sees that this one alone does not close it.
    small = an_area(name="Admin", floor_hours=Decimal(1))
    large = an_area(name="Fitness", floor_hours=Decimal(7))
    tight = FakeOffPlan([an_off_plan_period(interval=between(15, 24 * 4 + 24, day=2))])

    offers = offers_over(await an_assembly(areas=FakeAreas([small, large]), off_plan=tight))

    assert labels_of(by_kind(offers, AdjustmentKind.BREACH_FLOOR)) == [
        "Breach the Admin floor by 1h",
        "Breach the Fitness floor by 2h",
    ]


async def test_an_area_whose_floor_reserves_nothing_is_not_offered_a_breach() -> None:
    # An Area with no floor at all has nothing to give up, so offering it would be a row that
    # recovers nothing on a panel whose whole purpose is to show what closes the gap.
    fitness = an_area(name="Fitness", floor_hours=Decimal(7))
    unfloored = an_area(name="Admin")
    tight = FakeOffPlan([an_off_plan_period(interval=between(15, 24 * 4 + 24, day=2))])

    offers = offers_over(await an_assembly(areas=FakeAreas([fitness, unfloored]), off_plan=tight))

    assert labels_of(by_kind(offers, AdjustmentKind.BREACH_FLOOR)) == [
        "Breach the Fitness floor by 1h"
    ]


# --------------------------------------------------------------------------------
# A demand against its deadline
# --------------------------------------------------------------------------------


async def a_deadline_the_week_cannot_reach(**overrides: object) -> SolveInputs:
    """Four hours of Career work due Wednesday 10:00, with one hour of capacity before it.

    The Fitness floor of five hours has nowhere after the deadline to fit, so it is reserved before
    it and the shortfall honors it. That is the PRD's own worked example, and it is what makes the
    breach of another Area's floor an option against a deadline gap.
    """
    career = an_area(name="Career")
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        title="F&F Past Papers",
        estimate_minutes=4 * MINUTES_PER_HOUR,
        deadline=DEADLINE,
    )
    stated: dict[str, object] = {
        "areas": FakeAreas([fitness, career]),
        "tasks": FakeTasks([task]),
        "off_plan": FakeOffPlan([an_off_plan_period(interval=between(*REST_OF_THE_WEEK, day=2))]),
    }
    stated.update(overrides)
    return await an_assembly(**stated)


async def test_a_deadline_gap_offers_dropping_the_task_and_excusing_its_deadline() -> None:
    # Two different acts against one gap: the work can go, or the date it had to be done by can. The
    # user decides which of the two they can give up, which is the whole design of this panel.
    inputs = await a_deadline_the_week_cannot_reach()

    offers = offers_over(inputs)

    dropped = by_kind(offers, AdjustmentKind.DROP_ITEM)
    excused = by_kind(offers, AdjustmentKind.ACCEPT_PARTIAL)
    assert labels_of(dropped) == ["Drop F&F Past Papers this week"]
    assert labels_of(excused) == ["Accept partial delivery on F&F Past Papers"]
    assert [offer.tradeoff.target_id for offer in (*dropped, *excused)] == [
        CAREER_TASK,
        CAREER_TASK,
    ]


async def test_a_task_targeted_offer_recovers_the_gap_rather_than_the_whole_estimate() -> None:
    # The task holds four hours and the gap is two, because two hours of capacity are left before
    # the deadline. A concession states what it recovers against the gap it is offered for, so the
    # figure is the gap: claiming four would tell the user this closes more than the week is short.
    career = an_area(name="Career")
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=4 * MINUTES_PER_HOUR,
        deadline=at(11, day=2),
    )

    inputs = await an_assembly(
        areas=FakeAreas([career]),
        tasks=FakeTasks([task]),
        off_plan=FakeOffPlan([an_off_plan_period(interval=between(11, 24 * 5 + 24, day=2))]),
    )
    gap = next(
        one
        for one in probe(inputs.for_probe()).shortfalls
        if one.kind is ShortfallKind.DEADLINE_CAPACITY
    )

    offers = offers_over(inputs)

    assert gap.minutes == 2 * MINUTES_PER_HOUR
    assert inputs.eligible_tasks[0].remaining_minutes == 4 * MINUTES_PER_HOUR
    assert {offer.recovers for offer in by_kind(offers, AdjustmentKind.DROP_ITEM)} == {
        2 * MINUTES_PER_HOUR
    }


async def test_a_deadline_gap_offers_a_breach_of_the_floor_it_honored() -> None:
    # The PRD's own worked example: short after honoring the Fitness floor, so breaching that floor
    # is one of the options. The floor took capacity from the window this check measured, which is
    # what the honored list records.
    #
    # Enumerated over that gap alone, because this week holds three and the same breach answers more
    # than one of them: the figure a panel shows is the largest, and the claim here is about which
    # gap makes the breach applicable at all.
    inputs = await a_deadline_the_week_cannot_reach()
    verdict = probe(inputs.for_probe())
    gap = next(one for one in verdict.shortfalls if one.kind is ShortfallKind.DEADLINE_CAPACITY)

    offers = offered_tradeoffs(inputs, replace(verdict, shortfalls=(gap,)))

    assert "the Fitness floor of 5h" in gap.honoring
    assert gap.minutes == 4 * MINUTES_PER_HOUR
    assert labels_of(by_kind(offers, AdjustmentKind.BREACH_FLOOR)) == [
        "Breach the Fitness floor by 4h"
    ]


async def test_a_floor_the_deadline_gap_did_not_honor_is_not_offered_for_breach() -> None:
    # The case that makes the honored list load-bearing rather than decorative. With the rest of the
    # week left on plan the Fitness floor has sixty hours to fit into after Thursday, so it takes
    # nothing from the capacity before the deadline and breaching it recovers nothing. Offered
    # anyway, it would be a button that changes no figure.
    career = an_area(name="Career")
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=40 * MINUTES_PER_HOUR,
        deadline=at(10, day=1),
    )

    inputs = await an_assembly(areas=FakeAreas([fitness, career]), tasks=FakeTasks([task]))
    verdict = probe(inputs.for_probe())
    offers = offers_over(inputs)

    deadline_gap = next(
        one for one in verdict.shortfalls if one.kind is ShortfallKind.DEADLINE_CAPACITY
    )
    assert not any("floor of" in phrase for phrase in deadline_gap.honoring)
    assert by_kind(offers, AdjustmentKind.BREACH_FLOOR) == []


# --------------------------------------------------------------------------------
# A floor against its own Area
# --------------------------------------------------------------------------------


async def test_an_unreachable_floor_offers_a_breach_of_that_floor_and_no_other() -> None:
    # This check compares one Area's reservation against what it may claim, so the floor the user
    # would be breaching is that Area's own. Another Area's floor is not competition for it: the
    # check counts the other Areas' DEMANDS.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career", floor_hours=Decimal(1))
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=9 * MINUTES_PER_HOUR,
        deadline=at(10, day=4),
    )
    tight = FakeOffPlan([an_off_plan_period(interval=between(19, 24 * 4 + 24, day=2))])

    inputs = await an_assembly(
        areas=FakeAreas([fitness, career]), tasks=FakeTasks([task]), off_plan=tight
    )
    verdict = probe(inputs.for_probe())
    offers = offers_over(inputs)

    unreachable = next(
        one for one in verdict.shortfalls if one.kind is ShortfallKind.AREA_FLOOR_UNREACHABLE
    )
    assert unreachable.area_id == fitness.id
    breaches = by_kind(offers, AdjustmentKind.BREACH_FLOOR)
    assert [offer.tradeoff.target_id for offer in breaches] == [fitness.id]


async def test_an_unreachable_floor_offers_dropping_the_other_areas_work_that_competed() -> None:
    # The competition is what took the capacity this floor needed, so removing one of those demands
    # is what gives the floor room. Its own Area's work is not competition: a block placed for a
    # Fitness task lands in Fitness and satisfies the Fitness floor.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career")
    competing = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        title="F&F Past Papers",
        estimate_minutes=9 * MINUTES_PER_HOUR,
        deadline=at(10, day=4),
    )
    own = a_task(
        task_id=OTHER_TASK,
        area_id=fitness.id,
        title="Gym plan",
        estimate_minutes=MINUTES_PER_HOUR,
        deadline=at(10, day=4),
    )
    tight = FakeOffPlan([an_off_plan_period(interval=between(19, 24 * 4 + 24, day=2))])

    offers = offers_over(
        await an_assembly(
            areas=FakeAreas([fitness, career]),
            tasks=FakeTasks([competing, own]),
            off_plan=tight,
        )
    )

    unreachable_offers = [
        offer.tradeoff.target_id
        for offer in by_kind(offers, AdjustmentKind.DROP_ITEM)
        if offer.tradeoff.target_id == CAREER_TASK
    ]
    assert unreachable_offers == [CAREER_TASK]


# --------------------------------------------------------------------------------
# Shortening an elastic routine
# --------------------------------------------------------------------------------


async def a_week_needing_the_sleep_concession(**overrides: object) -> SolveInputs:
    """The ``elastic_sleep`` week: a sixty-minute gap against twenty minutes of give a night.

    The gap is a floor the week cannot hold. From Tuesday morning the week has 94 hours of free
    capacity, of which sleep takes none that is left, so a floor of 95 hours is short by exactly the
    fixture's sixty minutes. A floor that size is not a plausible declaration: what is under test is
    the arithmetic, and the gap has to be the fixture's figure for the distribution to be readable.
    """
    fitness = an_area(name="Fitness", floor_hours=Decimal(95))
    stated: dict[str, object] = {
        "areas": FakeAreas([fitness]),
        "routines": FakeRoutines([elastic_sleep_routine()]),
        "now": elastic_sleep.NOW,
    }
    stated.update(overrides)
    return await an_assembly(**stated)


async def test_the_reduce_routine_offer_names_the_nights_and_what_each_gives_up() -> None:
    # The fixture's own expectation, asserted through the enumerator: three nights at twenty minutes
    # each, named in the label because the concession stores them.
    inputs = await a_week_needing_the_sleep_concession()

    offers = offers_over(inputs)

    reductions = by_kind(offers, AdjustmentKind.REDUCE_ROUTINE)
    assert len(reductions) == 1
    offer = reductions[0]
    assert offer.tradeoff.label == elastic_sleep.LABEL
    assert offer.reductions == elastic_sleep.REDUCTIONS
    assert offer.recovers == elastic_sleep.GAP_MINUTES


async def test_a_routine_whose_minimum_equals_its_target_is_never_offered() -> None:
    # Which by default is every routine: the sleep floor is an elastic minimum the user sets, and a
    # routine with no give below its target has nothing to concede.
    inputs = await a_week_needing_the_sleep_concession(
        routines=FakeRoutines(
            [elastic_sleep_routine(min_duration_minutes=elastic_sleep.DURATION_MINUTES)]
        )
    )

    offers = offers_over(inputs)

    assert probe(inputs.for_probe()).shortfalls != ()
    assert by_kind(offers, AdjustmentKind.REDUCE_ROUTINE) == []


async def test_a_night_the_week_has_already_spent_is_not_offered() -> None:
    # A reduction moves an occurrence's end, and the probe counts no capacity before `now`, so
    # shortening Monday night would report time the week does not get back.
    inputs = await a_week_needing_the_sleep_concession()

    offer = by_kind(offers_over(inputs), AdjustmentKind.REDUCE_ROUTINE)[0]

    assert WEEK.dates()[0] not in offer.reductions
    assert min(offer.reductions) == elastic_sleep.TUESDAY


async def test_a_reduction_answering_a_deadline_names_only_nights_before_it() -> None:
    # Time handed back on Thursday night cannot be spent on work due Thursday morning, so a gap
    # measured before a deadline is only answerable with the nights that end before it.
    career = an_area(name="Career")
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=40 * MINUTES_PER_HOUR,
        deadline=at(10, day=3),
    )

    inputs = await an_assembly(
        areas=FakeAreas([career]),
        tasks=FakeTasks([task]),
        routines=FakeRoutines([elastic_sleep_routine()]),
        now=elastic_sleep.NOW,
    )

    offer = by_kind(offers_over(inputs), AdjustmentKind.REDUCE_ROUTINE)[0]
    assert set(offer.reductions) == {elastic_sleep.TUESDAY, elastic_sleep.WEDNESDAY}
    # Two nights, so the gap cannot be reached: the offer states what the nights can give rather
    # than the gap, and the user reads a figure that does not close it.
    assert offer.recovers == 2 * elastic_sleep.GIVE_MINUTES


async def test_a_gap_larger_than_the_give_takes_every_night_it_can_reach() -> None:
    # Six nights of twenty minutes against a gap of six hours: every night is used at its full give
    # and the offer recovers less than the gap, which is the honest answer rather than no offer at
    # all. The user reads two hours against a six-hour gap and sees that sleep alone will not do it.
    inputs = await a_week_needing_the_sleep_concession(
        areas=FakeAreas([an_area(name="Fitness", floor_hours=Decimal(100))])
    )

    offer = by_kind(offers_over(inputs), AdjustmentKind.REDUCE_ROUTINE)[0]

    assert len(offer.reductions) == 6
    assert set(offer.reductions.values()) == {elastic_sleep.GIVE_MINUTES}
    assert offer.recovers == 6 * elastic_sleep.GIVE_MINUTES


# --------------------------------------------------------------------------------
# What the enumerator does not do
# --------------------------------------------------------------------------------


async def test_a_concession_already_applied_this_week_is_not_offered_again() -> None:
    # The verdict panel lists it as an applied concession instead, so a week that absorbed one does
    # not read as simply feasible and the same button is not offered twice.
    fitness, career = a_week_the_floors_do_not_fit_in()
    tight = FakeOffPlan([an_off_plan_period(interval=between(15, 24 * 4 + 24, day=2))])
    applied = an_adjustment(
        kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=30
    )

    inputs = await an_assembly(
        areas=FakeAreas([fitness, career]),
        off_plan=tight,
        adjustments=FakeAdjustments([applied]),
    )
    offers = offers_over(inputs)

    assert [offer.tradeoff.target_id for offer in by_kind(offers, AdjustmentKind.BREACH_FLOOR)] == [
        career.id
    ]


async def test_a_candidate_being_evaluated_is_not_offered_again_either() -> None:
    # A candidate is applied to the assembly it rides on, so offering it again would invite the user
    # to compound a concession they have not yet approved. Thirty minutes rather than a figure this
    # enumerator would offer, so the Area still has floor left to breach and the suppression is what
    # keeps it off the panel rather than an exhausted target.
    fitness, career = a_week_the_floors_do_not_fit_in()
    tight = FakeOffPlan([an_off_plan_period(interval=between(15, 24 * 4 + 24, day=2))])
    candidate = WeekAdjustment(
        adjustment_id=uuid4(),
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=fitness.id,
        delta_minutes=30,
    )

    evaluated = await an_assembler(areas=FakeAreas([fitness, career]), off_plan=tight).assemble(
        WEEK, NOW, candidate
    )
    offers = offers_over(evaluated)

    assert evaluated.areas[0].floor_reservation_minutes > 0
    assert [offer.tradeoff.target_id for offer in by_kind(offers, AdjustmentKind.BREACH_FLOOR)] == [
        career.id
    ]


async def test_a_week_with_no_gap_is_offered_nothing() -> None:
    # Nothing to close, so nothing to offer. The panel says capacity is sufficient and stops.
    inputs = await an_assembly(areas=FakeAreas([an_area(name="Fitness", floor_hours=Decimal(1))]))

    assert probe(inputs.for_probe()).shortfalls == ()
    assert offers_over(inputs) == ()


async def test_enumerating_twice_over_one_assembly_gives_one_answer() -> None:
    # Deterministic, which it could not be if an identifier were minted here: an offer is a value
    # derived from one assembly, and the candidate's identity is supplied by whoever requests it.
    inputs = await a_deadline_the_week_cannot_reach()

    assert offers_over(inputs) == offers_over(inputs)


async def test_the_enumeration_changes_neither_the_inputs_nor_the_verdict() -> None:
    # syncr never selects one, and it mutates nothing on the way to not selecting: the tradeoff a
    # user picks becomes a candidate concession the assembly folds, and the fold is the only thing
    # that changes a figure. Asserted against a second assembly of the SAME stored state, so the
    # comparison is about the enumeration rather than about two sets of generated identifiers.
    career = an_area(name="Career")
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=4 * MINUTES_PER_HOUR,
        deadline=DEADLINE,
    )
    assembler = an_assembler(
        areas=FakeAreas([fitness, career]),
        tasks=FakeTasks([task]),
        off_plan=FakeOffPlan([an_off_plan_period(interval=between(*REST_OF_THE_WEEK, day=2))]),
    )
    inputs = await assembler.assemble(WEEK, NOW)
    verdict = probe(inputs.for_probe())

    offers = offered_tradeoffs(inputs, verdict)

    assert len(offers) > 1
    assert inputs == await assembler.assemble(WEEK, NOW)
    assert probe(inputs.for_probe()) == verdict


async def test_every_offer_states_a_positive_recovery() -> None:
    # "Every tradeoff recovers a stated number of minutes, so the user can see which ones actually
    # close the gap." A row recovering nothing, or an unstated figure, is worse than no row.
    shapes = (
        await a_deadline_the_week_cannot_reach(),
        await a_week_needing_the_sleep_concession(),
    )

    for inputs in shapes:
        offers = offers_over(inputs)
        assert offers != ()
        assert all(offer.tradeoff.delta_minutes is not None for offer in offers)
        assert all(offer.recovers > 0 for offer in offers)


async def test_every_gap_of_an_ordinary_week_is_answered_with_at_least_one_tradeoff() -> None:
    # A shortfall with no enumerable tradeoff is a bug rather than a valid state: the panel would
    # report an impossible week and offer nothing to do about it. Three shapes, each gap enumerated
    # alone so no other gap's offers can cover for it.
    #
    # **This is a rule with one exception, and the exception is drawn below** by
    # `test_a_demand_whose_task_has_no_eligible_row_is_answered_with_nothing`: a demand whose task
    # is not eligible has no target for either task-targeted kind, so a week holding nothing else
    # to concede answers that gap with nothing and says so in the log.
    fitness, career = a_week_the_floors_do_not_fit_in()
    tight = FakeOffPlan([an_off_plan_period(interval=between(19, 24 * 4 + 24, day=2))])
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=9 * MINUTES_PER_HOUR,
        deadline=at(10, day=2),
    )
    shapes = (
        await a_deadline_the_week_cannot_reach(),
        await a_week_needing_the_sleep_concession(),
        await an_assembly(
            areas=FakeAreas([fitness, career]), tasks=FakeTasks([task]), off_plan=tight
        ),
    )

    for inputs in shapes:
        verdict = probe(inputs.for_probe())
        assert verdict.shortfalls != ()
        for shortfall in verdict.shortfalls:
            assert offered_tradeoffs(inputs, replace(verdict, shortfalls=(shortfall,))) != ()


@pytest.fixture
def captured_log() -> Iterator[io.StringIO]:
    """Render to a captured stream, then hand the configuration back.

    Logging configuration is process-global, and ``conftest.py`` fails the test that leaves it
    changed, so the restore is part of the fixture rather than an afterthought.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


async def test_a_demand_whose_task_has_no_eligible_row_is_answered_with_nothing(
    captured_log: io.StringIO,
) -> None:
    # The exception to the rule above, one user pin away from an ordinary week, and the reason it
    # exists: eligibility nets immovable placements WHEREVER they sit and the demand nets only those
    # before the deadline, so a pin the user made after the deadline empties eligibility and leaves
    # the demand standing. Neither task-targeted kind can name a task eligibility does not carry.
    #
    # Recorded rather than fixed here: closing it needs the demand to carry its tasks' identities,
    # which is a field on the probe's own input struct and the same field the recovery-figure bounds
    # want. What ships is that the gap is answered with nothing and SAYS so, because a panel
    # reporting a gap with no button is otherwise invisible in production.
    career = an_area(name="Career")
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        title="F&F Past Papers",
        estimate_minutes=4 * MINUTES_PER_HOUR,
        deadline=at(10, day=2),
    )
    pinned = FakePlacements(
        pins=[
            a_pin(
                binding=BindingRef.for_task(CAREER_TASK),
                interval=between(9, 13, day=3),
                pinned_on=WEEK.dates()[2],
            )
        ]
    )

    inputs = await an_assembly(
        areas=FakeAreas([career]), tasks=FakeTasks([task]), placements=pinned
    )
    verdict = probe(inputs.for_probe())

    offers = offered_tradeoffs(inputs, verdict)

    assert inputs.eligible_tasks == ()
    assert [one.remaining_minutes for one in inputs.deadline_demands] == [4 * MINUTES_PER_HOUR]
    gap = next(one for one in verdict.shortfalls if one.kind is ShortfallKind.DEADLINE_CAPACITY)
    assert gap.minutes == 3 * MINUTES_PER_HOUR
    assert offers == ()
    # The one thing that makes the silence visible outside this request.
    assert "plans.tradeoff.gap_unanswered" in captured_log.getvalue()
    assert '"shortfall_kind": "deadline_capacity"' in captured_log.getvalue()


async def test_the_kinds_come_in_the_order_the_product_lists_them() -> None:
    # Drop, reduce, breach, accept: the order the PRD's own worked example enumerates them in, which
    # is the vocabulary's declaration order rather than a second ordering to maintain. Per gap,
    # because the panel lists each gap's own options.
    #
    # A week where all four apply at once: forty hours of Career work due Thursday morning, a
    # Fitness floor with nowhere after it to fit, and two elastic nights before it.
    career = an_area(name="Career")
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=40 * MINUTES_PER_HOUR,
        deadline=at(10, day=3),
    )

    inputs = await an_assembly(
        areas=FakeAreas([fitness, career]),
        tasks=FakeTasks([task]),
        routines=FakeRoutines([elastic_sleep_routine()]),
        off_plan=FakeOffPlan([an_off_plan_period(interval=between(10, 24 * 4 + 24, day=3))]),
        now=elastic_sleep.NOW,
    )
    verdict = probe(inputs.for_probe())
    gap = next(one for one in verdict.shortfalls if one.kind is ShortfallKind.DEADLINE_CAPACITY)

    offered = [
        offer.tradeoff.kind
        for offer in offered_tradeoffs(inputs, replace(verdict, shortfalls=(gap,)))
    ]

    assert set(offered) == set(AdjustmentKind)
    assert offered == sorted(offered, key=list(AdjustmentKind).index)


async def test_one_concession_offered_against_two_gaps_states_the_larger_recovery() -> None:
    # A concession is keyed by its kind and target, so it can only be approved once. Offering it
    # twice with two figures would leave the panel showing one button under two promises, and the
    # smaller of the two would understate what the user is approving.
    inputs = await a_deadline_the_week_cannot_reach()
    verdict = probe(inputs.for_probe())

    breach = next(
        offer
        for offer in offered_tradeoffs(inputs, verdict)
        if offer.tradeoff.kind is AdjustmentKind.BREACH_FLOOR
    )

    # What that one concession recovers against each gap separately, which is what the kept figure
    # is the largest of.
    per_gap = [
        offer.recovers
        for shortfall in verdict.shortfalls
        for offer in offered_tradeoffs(inputs, replace(verdict, shortfalls=(shortfall,)))
        if offer.concession == breach.concession
    ]
    assert len(per_gap) > 1
    assert len(set(per_gap)) > 1
    assert breach.recovers == max(per_gap)


# --------------------------------------------------------------------------------
# The gap capacity arithmetic cannot find
# --------------------------------------------------------------------------------


async def test_a_packing_failure_offers_the_task_it_names() -> None:
    # The one shortfall kind the probe cannot produce: the capacity exists and no single piece of
    # it is long enough, so a verdict is built by hand. The task is matched by the name the
    # shortfall renders, because a chunk failure is raised against a candidate rather than against
    # a demand grouped by Area and deadline.
    inputs = await a_deadline_the_week_cannot_reach()
    verdict = Verdict(
        feasible=False,
        provenance=Provenance.SOLVER,
        computed_at=NOW,
        input_version=inputs.input_version,
        discretionary_minutes=0,
        shortfalls=(
            minimum_chunk_shortfall(
                minutes=50,
                chunk_minutes=50,
                against=("F&F Past Papers",),
                area_id=inputs.eligible_tasks[0].area_id,
            ),
        ),
    )

    offers = offered_tradeoffs(inputs, verdict)

    assert [offer.tradeoff.kind for offer in offers] == [
        AdjustmentKind.DROP_ITEM,
        AdjustmentKind.ACCEPT_PARTIAL,
    ]
    assert {offer.tradeoff.target_id for offer in offers} == {CAREER_TASK}


@pytest.mark.parametrize("kind", list(AdjustmentKind))
def test_an_offer_names_the_kind_and_target_a_request_asks_for(kind: AdjustmentKind) -> None:
    # The identity a request names, and the one the storage index is keyed by. Bounded by the
    # vocabulary rather than by a list maintained here, so a fifth kind cannot arrive without a
    # decision at this boundary.
    target = uuid4()

    offer = Offer(tradeoff=Tradeoff(kind=kind, label="stated", target_id=target, delta_minutes=30))

    assert offer.concession == (kind, target)
    assert offer.recovers == 30
    assert offer.reductions == {}
