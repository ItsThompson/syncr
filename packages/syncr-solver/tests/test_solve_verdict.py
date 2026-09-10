"""Phase 5: the verdict, and the transition only an attempted placement can find.

The derivation under test is one sentence: the probe's shortfalls plus one packing failure per
deadline-bearing demand the attempt could not place. So the tests come in three groups: that the
probe's half is carried through, that the synthesised half exists at all, and that the two together
produce the transition on a week that passes the arithmetic and fails to pack.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_domain.feasibility import DeadlineDemand, Provenance, ShortfallKind, probe
from syncr_solver.constraints import ConstraintRule
from syncr_solver.inputs import FrameOverhang
from tests.materialized_weeks import CAREER, a_frame_entry, an_area_budget, between
from tests.objective_weeks import ANOTHER_TASK, an_eligible_task, an_occurrence
from tests.solve_weeks import a_week, blocks_titled, solved

if TYPE_CHECKING:
    from syncr_solver.inputs import SolveInputs

DEADLINE = between(9, 10, day=5).start


def a_week_that_packs_only_in_half_hour_pieces(**kwargs: object) -> SolveInputs:
    """A week whose only discretionary time is four half-hour gaps on the Monday.

    The frame fills everything else, so the capacity totals 120 minutes and no single piece of it is
    longer than thirty. That is the shape capacity arithmetic cannot see: the totals are sufficient
    and the shape is not.
    """
    frame = (
        a_frame_entry(day=0, interval=between(0, 9)),
        a_frame_entry(day=0, interval=between(9.5, 10), routine_id=uuid4()),
        a_frame_entry(day=0, interval=between(10.5, 11), routine_id=uuid4()),
        a_frame_entry(day=0, interval=between(11.5, 12), routine_id=uuid4()),
        a_frame_entry(day=0, interval=between(12.5, 24), routine_id=uuid4()),
        *(
            a_frame_entry(day=day, interval=between(0, 24, day=day), routine_id=uuid4())
            for day in range(1, 7)
        ),
    )
    return a_week(
        frame=frame,
        eligible_tasks=(
            an_eligible_task(
                task_id=ANOTHER_TASK,
                remaining_minutes=120,
                min_chunk_minutes=50,
                area_id=CAREER,
                title="F&F Past Papers",
                deadline=DEADLINE,
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# What a solver verdict may claim, and where its two halves come from
# --------------------------------------------------------------------------------------


def test_a_solve_carries_inherited_frame_occupancy_into_its_document() -> None:
    """A following week's budget must retain the preceding night's occupied minutes."""
    inherited = between(0, 1)
    week = a_week(frame_overhang=(FrameOverhang(interval=inherited),))

    result = solved(week)

    assert [entry.interval for entry in result.document.frame_overhang] == [inherited]


def test_a_solver_verdict_is_authoritative_where_a_probe_verdict_may_not_be() -> None:
    """A probe verdict cannot claim a week works; a solve attempted the placement and knows."""
    week = a_week(
        eligible_tasks=(an_eligible_task(remaining_minutes=60),),
        areas=(an_area_budget(target_minutes=600),),
    )

    verdict = solved(week).verdict

    assert verdict.provenance is Provenance.SOLVER
    assert verdict.feasible is True
    assert verdict.shortfalls == ()


def test_the_probes_own_shortfalls_are_carried_into_the_solver_verdict() -> None:
    """The panel and the backlog share one computation, so the capacity half is not re-derived."""
    week = a_week(
        areas=(
            an_area_budget(
                area_id=CAREER,
                name="Career",
                floor_minutes=60 * 24 * 8,
                target_minutes=60 * 24 * 8,
            ),
        ),
    )

    verdict = solved(week).verdict
    arithmetic = probe(week.for_probe())

    assert arithmetic.shortfalls
    assert verdict.shortfalls == arithmetic.shortfalls
    assert verdict.feasible is False


def test_the_weeks_denominator_is_the_probes_rather_than_a_second_subtraction() -> None:
    week = a_week_that_packs_only_in_half_hour_pieces()

    arithmetic = probe(week.for_probe())

    assert solved(week).verdict.discretionary_minutes == arithmetic.discretionary_minutes


# --------------------------------------------------------------------------------------
# A week that passes the probe and fails to pack
# --------------------------------------------------------------------------------------


def test_a_week_that_passes_the_probe_and_fails_to_pack_reports_the_packing_failure() -> None:
    week = a_week_that_packs_only_in_half_hour_pieces(
        deadline_demands=(
            DeadlineDemand(
                deadline=DEADLINE,
                remaining_minutes=120,
                area_id=CAREER,
                labels=("F&F Past Papers",),
            ),
        )
    )

    arithmetic = probe(week.for_probe())
    result = solved(week)

    assert arithmetic.capacity_is_sufficient, "the probe must find nothing for this to be S8"
    assert blocks_titled(result.document, "F&F Past Papers") == ()
    assert [shortfall.kind for shortfall in result.verdict.shortfalls] == [
        ShortfallKind.MINIMUM_CHUNK_UNPLACEABLE
    ]
    assert result.verdict.provenance is Provenance.SOLVER
    assert result.verdict.feasible is False


def test_a_capacity_shortfall_is_not_duplicated_as_a_packing_failure() -> None:
    """One deadline cannot need two tradeoffs for the same unavailable capacity."""
    week = a_week_that_packs_only_in_half_hour_pieces(
        deadline_demands=(
            DeadlineDemand(
                deadline=DEADLINE,
                remaining_minutes=180,
                area_id=CAREER,
                labels=("F&F Past Papers",),
            ),
        )
    )

    result = solved(week)

    assert [shortfall.kind for shortfall in result.verdict.shortfalls] == [
        ShortfallKind.DEADLINE_CAPACITY
    ]


def test_the_packing_failure_names_the_minutes_unplaced_rather_than_the_whole_demand() -> None:
    """A shortfall is the gap a tradeoff has to recover, not the work the week owes."""
    week = a_week_that_packs_only_in_half_hour_pieces()

    shortfall = solved(week).verdict.shortfalls[0]

    assert shortfall.minutes == 120
    assert shortfall.against == ("F&F Past Papers",)
    assert shortfall.deadline == DEADLINE
    assert shortfall.area_id == CAREER


def test_the_packing_failure_honors_the_minimum_chunk_first_and_then_what_refused_it() -> None:
    """The minimum chunk is the declaration the user can act on, so it is named first."""
    week = a_week_that_packs_only_in_half_hour_pieces()

    result = solved(week)
    shortfall = result.verdict.shortfalls[0]

    assert shortfall.honoring[0] == "its 50m minimum chunk"
    assert any(ConstraintRule.BELOW_MIN_CHUNK.value in named for named in shortfall.honoring[1:])
    assert len(shortfall.honoring) == 1 + len(result.blocked_log)


def test_a_task_the_solve_placed_in_full_produces_no_packing_failure() -> None:
    """The control for the synthesis: a refusal on the way is not a demand left short."""
    week = a_week(
        eligible_tasks=(
            an_eligible_task(
                remaining_minutes=60, area_id=CAREER, title="Papers", deadline=DEADLINE
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", max_per_day_minutes=60),),
    )

    result = solved(week)

    assert blocks_titled(result.document, "Papers")
    assert result.verdict.shortfalls == ()


def test_a_task_with_no_deadline_the_solve_could_not_place_produces_no_shortfall() -> None:
    """Found by a bite that made every task deadline-bearing and reddened nothing: a missing test.

    A shortfall is a gap measured against something, and the four kinds all name work that has to
    fit before an instant. Work with no deadline is not late, so it is charged by the objective and
    the verdict says nothing about it. Synthesised anyway, the panel would report a gap the user
    cannot act on and no tradeoff can close.
    """
    week = a_week_that_packs_only_in_half_hour_pieces()
    undated = replace(week, eligible_tasks=(replace(week.eligible_tasks[0], deadline=None),))

    result = solved(undated)

    assert blocks_titled(result.document, "F&F Past Papers") == ()
    assert result.blocked_log, "the task has to have been refused for this to mean anything"
    assert result.verdict.shortfalls == ()
    assert result.verdict.feasible is True


def test_a_demand_with_no_deadline_is_charged_by_the_objective_rather_than_by_a_shortfall() -> None:
    """A shortfall is a gap measured against something, and a habit has nothing to be late for."""
    week = a_week(
        frame=(
            a_frame_entry(day=0, interval=between(0, 24)),
            *(
                a_frame_entry(day=day, interval=between(0, 24, day=day), routine_id=uuid4())
                for day in range(1, 7)
            ),
        ),
        habit_occurrences=(an_occurrence(minutes=60),),
        areas=(an_area_budget(target_minutes=600),),
    )

    result = solved(week)

    assert blocks_titled(result.document, "Gym") == ()
    assert result.verdict.shortfalls == ()
    assert result.objective_breakdown.staleness > 0
