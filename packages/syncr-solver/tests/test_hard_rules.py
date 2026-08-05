"""One property per hard constraint, and the demonstration that each property can fail.

The acceptance the checker owes is not that it refuses a candidate: it is that **no plan built
through it violates a rule**. So each property here places candidates through
:class:`~syncr_solver.constraints.ConstraintCheck` and then judges the resulting plan against an
oracle stated over the whole plan, independently of the rule function that produced it.

**A checker is an instrument, and an instrument is worthless until it has been shown to fail.** A
property asserting that a plan holds no violation passes just as happily against an oracle that
cannot see one. So every property is paired with a scenario that violates its rule, placed twice:
once through all thirteen rules, where the oracle must find nothing, and once through the twelve
without it, where the oracle must find the violation. That pairing is what makes a null result mean
something, and it also proves each of the thirteen rules has a reachable violation, which is the
condition a member of the vocabulary earns its place by.

The oracles deliberately restate their rules at plan level rather than calling them. A property
whose oracle is the implementation asserts only that the implementation equals itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from random import Random
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from syncr_domain.gaps import ForbiddenKind, ForbiddenScope
from syncr_domain.identity import BindingKind, BindingRef, TransitLeg
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.snap import SNAP, is_on_snap_grid
from syncr_solver.constraints import Blocked, ConstraintCheck, ConstraintRule
from syncr_solver.occupancy import DERIVED_FROM_AN_ANCHOR
from syncr_solver.rules import HARD_RULES, RULE_BY_NAME
from syncr_solver.shape import EXEMPT_FROM_THE_SNAP
from syncr_solver.state import PartialPlan, Placement, Sizing
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    a_block,
    a_candidate,
    a_frame_entry,
    a_live_plan,
    a_pin,
    a_recovery_window,
    a_sizing,
    a_transit_block,
    an_anchor,
    an_area_budget,
    an_off_plan_period,
    at,
    between,
    inputs,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_solver.constraints import Rule
    from syncr_solver.inputs import SolveInputs

GYM = BindingRef.for_task(UUID(int=31))
READING = BindingRef.for_task(UUID(int=32))
STANDUP = BindingRef.for_task(UUID(int=33))
AN_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000bb")

HOUR = 60


# --------------------------------------------------------------------------------
# Placing a plan through the checker
# --------------------------------------------------------------------------------


def place(offered: Sequence[Placement], state: PartialPlan, rules: Sequence[Rule]) -> Attempt:
    """Greedy placement: each candidate against the state, and the state grows by what is accepted.

    The same shape as a solve's own construction, reduced to what a constraint property needs: no
    objective, no ordering choice, no local search. What it produces is a plan whose every member
    was accepted by the rules in force, which is the only thing the properties below judge. The
    refusals come back too, because what a generator REACHED is a measurement rather than a guess.
    """
    check = ConstraintCheck(rules)
    placed: list[Placement] = []
    refused: list[Blocked] = []
    for candidate in offered:
        rejection = check.check(candidate, state)
        if rejection is not None:
            refused.append(rejection)
            continue
        state = state.with_placed(candidate)
        placed.append(candidate)
    return Attempt(placed=tuple(placed), state=state, refused=tuple(refused))


@dataclass(frozen=True, slots=True, kw_only=True)
class Attempt:
    """What a greedy pass produced: the plan, the state holding it, and every refusal."""

    placed: tuple[Placement, ...]
    state: PartialPlan
    refused: tuple[Blocked, ...]


# --------------------------------------------------------------------------------
# One oracle per rule, stated over the finished plan
# --------------------------------------------------------------------------------


def broke_h1(state: PartialPlan) -> bool:
    return any(
        anchor.interval.overlaps(placement.interval)
        for anchor in state.anchors
        for placement in state.placed
    )


def broke_h2(state: PartialPlan) -> bool:
    return any(
        window.scope is ForbiddenScope.ALL
        and window.interval.overlaps(placement.interval)
        and not exempt(window.kind, window.anchor_id, placement)
        for window in state.forbidden_windows
        for placement in state.placed
    )


def broke_h3(state: PartialPlan) -> bool:
    occupied = IntervalSet([*(entry.interval for entry in state.frame), *state.inherited])
    return any(occupied.overlaps(placement.interval) for placement in state.placed)


def broke_h4(state: PartialPlan) -> bool:
    for index, one in enumerate(state.placed):
        for other in state.placed[index + 1 :]:
            if not one.interval.overlaps(other.interval):
                continue
            if authored(one, state) or authored(other, state):
                continue
            return True
    return False


def broke_h6(state: PartialPlan) -> bool:
    return any(
        placement.sizing is not None
        and not placement.sizing.splittable
        and (
            placement.binding.split_index is not None
            or placement.minutes() < placement.sizing.whole_minutes
        )
        for placement in state.placed
    )


def broke_h7(state: PartialPlan) -> bool:
    return any(
        placement.sizing is not None
        and placement.sizing.splittable
        and placement.minutes() < placement.sizing.min_chunk_minutes
        for placement in state.placed
    )


def broke_h8(state: PartialPlan) -> bool:
    for area in state.areas:
        if area.max_per_day_minutes is None:
            continue
        claimed = IntervalSet(
            placement.interval
            for placement in state.placed
            if placement.area_id == area.area_id and not immovable_at(placement, state)
        )
        for day in state.days:
            if claimed.clip(day.interval).total_minutes() > area.max_per_day_minutes:
                return True
    return False


def broke_h9(state: PartialPlan) -> bool:
    """Whether the plan leaves less claimable time than the floors still unmet need.

    An invariant of the finished plan rather than of one candidate: H9 preserves it at every step,
    so the last accepted placement leaves it true. The weeks below all begin with it true, so a plan
    that breaks it broke it by placing something.

    Stated over what the solver CHOSE, because a placement it cannot move is not a choice: a plan
    has to hold its own past blocks whether or not the budgets close around them, and the last such
    placement would otherwise be blamed for a state the inputs arrived in.
    """
    chosen = tuple(placement for placement in state.placed if not immovable_at(placement, state))
    if not chosen:
        return False
    claimed = IntervalSet(
        placement.interval for placement in state.placed if placement.area_id is not None
    )
    free = state.discretionary().subtract(claimed).total_minutes()
    owed = sum(
        max(
            0,
            area.floor_minutes
            - IntervalSet(
                placement.interval
                for placement in chosen
                if placement.area_id == area.area_id
                and placement.binding not in state.started
                and placement.binding not in state.pins
            ).total_minutes(),
        )
        for area in state.areas
    )
    return owed > free


def broke_h10(state: PartialPlan) -> bool:
    return any(
        placement.binding in state.started
        and state.started[placement.binding].interval != placement.interval
        for placement in state.placed
    )


def broke_h11(state: PartialPlan) -> bool:
    return any(
        placement.binding in state.immovable
        and state.immovable[placement.binding].interval != placement.interval
        for placement in state.placed
    )


def broke_h12(state: PartialPlan) -> bool:
    return any(
        period.interval.overlaps(placement.interval) and not authored(placement, state)
        for period in state.off_plan
        for placement in state.placed
    )


def broke_h13(state: PartialPlan) -> bool:
    return any(
        window.scope is ForbiddenScope.AREAS
        and placement.area_id is not None
        and window.forbids(placement.area_id)
        and window.interval.overlaps(placement.interval)
        and not exempt(window.kind, window.anchor_id, placement)
        for window in state.forbidden_windows
        for placement in state.placed
    )


def broke_h14(state: PartialPlan) -> bool:
    return any(
        placement.binding.kind not in EXEMPT_FROM_THE_SNAP
        and not (
            is_on_snap_grid(placement.interval.start) and is_on_snap_grid(placement.interval.end)
        )
        for placement in state.placed
    )


def exempt(kind: ForbiddenKind, anchor_id: UUID, placement: Placement) -> bool:
    """Whether this placement is a buffer the commitment that cast the window derived."""
    return (
        kind is ForbiddenKind.RECOVERY
        and placement.binding.kind in DERIVED_FROM_AN_ANCHOR
        and placement.binding.entity_id == anchor_id
    )


def authored(placement: Placement, state: PartialPlan) -> bool:
    """Whether this placement is the user's own, at the interval the user chose."""
    return state.pins.get(placement.binding) == placement.interval


def immovable_at(placement: Placement, state: PartialPlan) -> bool:
    """Whether the week already held this content at exactly this span, so nothing chose it.

    The two allocation rules pass over such a placement, and so must the two oracles that judge
    them: a plan has to hold its own past blocks whether or not the budgets close around them.
    """
    for index in (state.started, state.immovable):
        held = index.get(placement.binding)
        if held is not None and held.interval == placement.interval:
            return True
    return False


ORACLE_BY_RULE = {
    ConstraintRule.ANCHOR_OVERLAP: broke_h1,
    ConstraintRule.FORBIDDEN_WINDOW: broke_h2,
    ConstraintRule.FRAME_OVERLAP: broke_h3,
    ConstraintRule.BLOCK_OVERLAP: broke_h4,
    ConstraintRule.ATOMIC_NOT_SPLITTABLE: broke_h6,
    ConstraintRule.BELOW_MIN_CHUNK: broke_h7,
    ConstraintRule.AREA_DAILY_CAP: broke_h8,
    ConstraintRule.AREA_FLOOR: broke_h9,
    ConstraintRule.PAST_BLOCK: broke_h10,
    ConstraintRule.IMMOVABLE_BLOCK: broke_h11,
    ConstraintRule.OFF_PLAN: broke_h12,
    ConstraintRule.FORBIDDEN_AREA: broke_h13,
    ConstraintRule.SNAP: broke_h14,
}


def test_the_oracles_cover_the_whole_vocabulary_and_nothing_outside_it() -> None:
    # Bounded by the inventory rather than by the rules anyone wrote a property for: a fourteenth
    # member fails here until it has an oracle, so the suite cannot silently cover twelve.
    assert set(ORACLE_BY_RULE) == set(ConstraintRule)


# --------------------------------------------------------------------------------
# A scenario per rule: the plan that breaks it, and the rule that stops it
# --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scenario:
    """One week, and candidates whose placement breaks exactly one rule.

    ``seeded`` is what the caller states the week already holds. It is the channel a solve carries
    its past blocks and pins in through, and two of the scenarios need it.
    """

    rule: ConstraintRule
    week: SolveInputs
    offered: tuple[Placement, ...]
    seeded: tuple[Placement, ...] = field(default_factory=tuple)


A_STARTED_GYM = a_block(binding=GYM, interval=between(8, 9), title="Gym")
A_TRANSIT = a_transit_block(anchor_id=AN_ANCHOR_ID, interval=between(9.5, 10))

# Everything from Monday 03:00 onwards is declared off, leaving three hours of claimable time, so a
# floor and a candidate are worked figures rather than fractions of a whole week.
NARROW = an_off_plan_period(interval=Interval(at(3), at(0, day=7)))

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        rule=ConstraintRule.ANCHOR_OVERLAP,
        week=inputs(anchors=(an_anchor(interval=between(10, 11)),)),
        offered=(a_candidate(between(10.5, 11.5), binding=READING),),
    ),
    Scenario(
        rule=ConstraintRule.FORBIDDEN_WINDOW,
        week=inputs(forbidden_windows=(a_recovery_window(interval=between(11, 12)),)),
        offered=(a_candidate(between(11, 11.5), binding=READING),),
    ),
    Scenario(
        rule=ConstraintRule.FRAME_OVERLAP,
        week=inputs(frame=(a_frame_entry(interval=between(23, 31)),)),
        offered=(a_candidate(between(23.5, 24), binding=READING),),
    ),
    Scenario(
        rule=ConstraintRule.BLOCK_OVERLAP,
        week=inputs(),
        offered=(
            a_candidate(between(10, 11), binding=GYM),
            a_candidate(between(10.5, 11.5), binding=READING),
        ),
    ),
    Scenario(
        rule=ConstraintRule.ATOMIC_NOT_SPLITTABLE,
        week=inputs(),
        offered=(
            a_candidate(
                between(10, 10.5),
                binding=READING,
                sizing=a_sizing(whole_minutes=HOUR, splittable=False),
            ),
        ),
    ),
    Scenario(
        rule=ConstraintRule.BELOW_MIN_CHUNK,
        week=inputs(),
        offered=(
            a_candidate(
                between(10, 10.25),
                binding=READING,
                sizing=a_sizing(whole_minutes=4 * HOUR, min_chunk_minutes=45),
            ),
        ),
    ),
    Scenario(
        rule=ConstraintRule.AREA_DAILY_CAP,
        week=inputs(areas=(an_area_budget(max_per_day_minutes=HOUR),)),
        offered=(
            a_candidate(between(8, 9), binding=GYM),
            a_candidate(between(10, 11), binding=READING),
        ),
    ),
    Scenario(
        rule=ConstraintRule.AREA_FLOOR,
        week=inputs(
            off_plan=(NARROW,),
            areas=(
                an_area_budget(floor_minutes=2 * HOUR),
                an_area_budget(area_id=CAREER, name="Career"),
            ),
        ),
        offered=(a_candidate(Interval(at(0), at(2)), area_id=CAREER, binding=READING),),
    ),
    Scenario(
        rule=ConstraintRule.PAST_BLOCK,
        week=inputs(live_plan=a_live_plan(A_STARTED_GYM)),
        offered=(a_candidate(between(14, 15), binding=GYM, title="Gym"),),
    ),
    Scenario(
        rule=ConstraintRule.IMMOVABLE_BLOCK,
        week=inputs(shadow_blocks=(A_TRANSIT,)),
        offered=(
            a_candidate(
                between(11, 11.5),
                binding=A_TRANSIT.binding,
                area_id=CAREER,
                title="Leave for Uni",
            ),
        ),
    ),
    Scenario(
        rule=ConstraintRule.OFF_PLAN,
        week=inputs(off_plan=(an_off_plan_period(interval=between(0, 48), label="Rome"),)),
        offered=(a_candidate(between(10, 11), binding=READING),),
    ),
    Scenario(
        rule=ConstraintRule.FORBIDDEN_AREA,
        week=inputs(
            forbidden_windows=(
                a_recovery_window(
                    interval=between(11, 12),
                    scope=ForbiddenScope.AREAS,
                    forbidden_area_ids=(FITNESS,),
                ),
            )
        ),
        offered=(a_candidate(between(11, 11.5), binding=READING),),
    ),
    Scenario(
        rule=ConstraintRule.SNAP,
        week=inputs(),
        offered=(
            a_candidate(
                Interval(at(10) + timedelta(minutes=7), at(11) + timedelta(minutes=7)),
                binding=READING,
            ),
        ),
    ),
)

BY_RULE = {scenario.rule: scenario for scenario in SCENARIOS}


def test_a_scenario_exists_for_every_rule_in_the_vocabulary() -> None:
    # The control on the two suites below: a rule with no scenario would be covered by neither, and
    # a rule whose violation nobody can construct is a member that cannot fire.
    assert set(BY_RULE) == set(ConstraintRule)
    assert len(SCENARIOS) == len(ConstraintRule)


@pytest.mark.parametrize("rule", list(ConstraintRule), ids=[rule.value for rule in ConstraintRule])
def test_no_plan_placed_through_every_rule_violates_any_of_them(rule: ConstraintRule) -> None:
    # Each scenario is legal under the twelve rules it is not built to break, so the plan a full
    # checker produces is clean against every oracle rather than only against its own.
    scenario = BY_RULE[rule]
    state = PartialPlan.of(scenario.week, placed=scenario.seeded)

    attempt = place(scenario.offered, state, HARD_RULES)

    broke = {named for named, oracle in ORACLE_BY_RULE.items() if oracle(attempt.state)}
    assert broke == set()


@pytest.mark.parametrize("rule", list(ConstraintRule), ids=[rule.value for rule in ConstraintRule])
def test_the_property_for_a_rule_fails_when_that_rule_is_not_in_force(
    rule: ConstraintRule,
) -> None:
    # The instrument shown to fail. Without this the suite above would pass against an oracle that
    # cannot see its own violation, and against a rule whose violation nothing can reach.
    scenario = BY_RULE[rule]
    without = tuple(check for check in HARD_RULES if check is not RULE_BY_NAME[rule])
    state = PartialPlan.of(scenario.week, placed=scenario.seeded)

    attempt = place(scenario.offered, state, without)

    assert len(without) == len(HARD_RULES) - 1
    assert attempt.placed, "the scenario placed nothing, so the oracle is judging an empty plan"
    assert ORACLE_BY_RULE[rule](attempt.state) is True


# --------------------------------------------------------------------------------
# The same properties over generated candidates, against one week that carries every shape
# --------------------------------------------------------------------------------

# A week holding every kind of thing a rule reads, so a generated candidate can break any of the
# thirteen. The floors are inside the claimable time by construction: a week whose floors already
# exceed its capacity would fail H9's property before anything was placed, which would be a
# statement about the fixture rather than about the checker.
RICH_WEEK = inputs(
    frame=(a_frame_entry(interval=between(23, 31)),),
    anchors=(an_anchor(anchor_id=AN_ANCHOR_ID, interval=between(10, 11)),),
    forbidden_windows=(
        a_recovery_window(interval=between(11, 12.25), anchor_id=AN_ANCHOR_ID),
        a_recovery_window(
            interval=between(14, 15),
            anchor_id=AN_ANCHOR_ID,
            scope=ForbiddenScope.AREAS,
            forbidden_area_ids=(FITNESS,),
        ),
    ),
    off_plan=(an_off_plan_period(interval=between(0, 6, day=5), label="Rome"),),
    shadow_blocks=(A_TRANSIT,),
    areas=(
        an_area_budget(floor_minutes=2 * HOUR, max_per_day_minutes=90),
        an_area_budget(area_id=CAREER, name="Career", floor_minutes=HOUR),
    ),
    pins=(a_pin(binding=STANDUP, interval=between(16, 17)),),
    live_plan=a_live_plan(A_STARTED_GYM),
)

# The bindings a candidate can carry, which deliberately include three the week already holds
# somewhere: a started block, a pin, and a buffer fixed by derivation.
BINDINGS = (
    GYM,
    READING,
    STANDUP,
    A_TRANSIT.binding,
    BindingRef.for_anchor_transit(UUID(int=41), leg=TransitLeg.BACK),
    BindingRef.for_habit(UUID(int=42), index=0),
)


def candidates() -> st.SearchStrategy[Placement]:
    """One candidate anywhere in the week, sometimes off the grid and sometimes too short.

    Drawn in quarter-hour steps with a deliberate minute offset some of the time, because a
    generator that only ever lands on the grid could not reach H14, and one that always placed a
    demand whole could not reach H6 or H7.
    """
    return st.builds(
        _a_drawn_candidate,
        step=st.integers(min_value=0, max_value=7 * 24 * 4 - 1),
        steps_long=st.integers(min_value=1, max_value=8),
        offset=st.sampled_from((0, 0, 0, 7)),
        area_id=st.sampled_from((FITNESS, CAREER, None)),
        binding=st.sampled_from(BINDINGS),
        whole_minutes=st.sampled_from((15, 30, 60, 240)),
        min_chunk_minutes=st.sampled_from((15, 45)),
        splittable=st.booleans(),
    )


def _a_drawn_candidate(
    *,
    step: int,
    steps_long: int,
    offset: int,
    area_id: UUID | None,
    binding: BindingRef,
    whole_minutes: int,
    min_chunk_minutes: int,
    splittable: bool,
) -> Placement:
    start = at(0) + SNAP * step + timedelta(minutes=offset)
    interval = Interval(start, start + SNAP * steps_long)
    sizing = (
        Sizing(
            whole_minutes=whole_minutes,
            min_chunk_minutes=min_chunk_minutes,
            splittable=splittable,
        )
        if binding.kind in {BindingKind.TASK, BindingKind.HABIT}
        else None
    )
    return Placement(
        binding=binding,
        interval=interval,
        title="Leetcode",
        area_id=None if binding.kind == BindingKind.ANCHOR_TRANSIT and area_id is None else area_id,
        sizing=sizing,
    )


@given(offered=st.lists(candidates(), min_size=1, max_size=12))
@settings(max_examples=200, deadline=None)
@pytest.mark.parametrize("rule", list(ConstraintRule), ids=[rule.value for rule in ConstraintRule])
def test_no_plan_of_generated_candidates_violates_any_rule(
    rule: ConstraintRule, offered: list[Placement]
) -> None:
    # The property section 20 asks for, one per rule, over generated inputs. Parametrized by rule so
    # a failure names the rule that was broken rather than reporting a single opaque red.
    attempt = place(offered, PartialPlan.of(RICH_WEEK), HARD_RULES)

    assert ORACLE_BY_RULE[rule](attempt.state) is False


def a_deterministic_sample(count: int) -> tuple[Placement, ...]:
    """``count`` candidates drawn from the same shape the generator draws, at a fixed seed.

    Deterministic rather than generated, because what follows is a measurement of the stream itself:
    hypothesis reports what it found and not what it covered, so a claim about reach has to be
    asserted over a stream this suite can name.
    """
    random = Random(20260207)  # noqa: S311 - a fixed draw of test candidates, not a secret
    return tuple(
        _a_drawn_candidate(
            step=random.randrange(7 * 24 * 4),
            steps_long=random.randrange(1, 9),
            offset=random.choice((0, 0, 0, 7)),
            area_id=random.choice((FITNESS, CAREER, None)),
            binding=random.choice(BINDINGS),
            whole_minutes=random.choice((15, 30, 60, 240)),
            min_chunk_minutes=random.choice((15, 45)),
            splittable=random.choice((True, False)),
        )
        for _ in range(count)
    )


# How many candidates the reach and share measurements below draw. Large enough that every rule a
# random draw can reach is reached: the thinnest is the scoped window, which covers one Area for one
# hour of the week and is refused once at this size.
SAMPLE = 2000


def test_the_generated_stream_reaches_every_rule_but_the_one_this_week_cannot_break() -> None:
    # A property over a stream that never reaches a rule is vacuous for that rule, so the reach is
    # asserted as an exact set rather than assumed. H9 is the one exception and it is structural:
    # this week holds three hours of floors against a hundred and sixty of claimable time, so no
    # sequence of non-overlapping placements can leave a floor unreachable. Its violation IS
    # reachable, and the scenario above proves it over a week whose whole capacity is three hours.
    attempt = place(a_deterministic_sample(SAMPLE), PartialPlan.of(RICH_WEEK), HARD_RULES)

    assert {rejection.rule for rejection in attempt.refused} == set(ConstraintRule) - {
        ConstraintRule.AREA_FLOOR
    }


def test_the_rich_week_admits_a_measurable_share_of_what_it_is_offered() -> None:
    # A fixture nothing can be placed in would make thirteen properties pass over an empty plan, and
    # that is exactly the failure the properties themselves cannot report.
    attempt = place(a_deterministic_sample(SAMPLE), PartialPlan.of(RICH_WEEK), HARD_RULES)

    assert len(attempt.placed) >= 50


def test_the_rich_week_admits_a_candidate_at_all() -> None:
    attempt = place(
        (a_candidate(between(8, 9), binding=READING),), PartialPlan.of(RICH_WEEK), HARD_RULES
    )

    assert len(attempt.placed) == 1
