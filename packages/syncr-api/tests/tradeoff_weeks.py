"""The week every tradeoff kind can be offered in, and the offer the enumerator makes for each.

Two suites drive a concession end to end and both need the same week: the fold's own suite, which
asserts what approving one MODIFIES, and the approval's, which asserts that the shortfall the panel
quoted has closed once the concession is a stored row. A second construction of the week would let
the two measure different arithmetic while claiming to measure one.

The week is deliberately tight in four ways at once, because a shape only three kinds apply to
cannot state a rule about four: forty hours of Career work due Thursday morning, a Fitness floor
with nowhere after it to fit, an elastic sleep routine with two reducible nights before the
deadline, and a preference on the task so the field the prose tables do not name is observable.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from syncr_api.plans.tradeoffs import offered_tradeoffs
from syncr_domain.feasibility import probe
from syncr_domain.fixtures import elastic_sleep
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind
from tests.assembly_fakes import (
    MINUTES_PER_HOUR,
    WEEK,
    FakeAreas,
    FakeOffPlan,
    FakePreferences,
    FakeRoutines,
    FakeTasks,
    a_preference,
    a_routine,
    a_task,
    an_area,
    an_assembler,
    an_off_plan_period,
    at,
    between,
)

if TYPE_CHECKING:
    from syncr_api.plans.assembler import WeekAssembler
    from syncr_api.plans.tradeoffs import Offer
    from syncr_domain.feasibility import Shortfall, ShortfallKind, Verdict
    from syncr_domain.identifiers import AreaId, TaskId
    from syncr_domain.plan import AdjustmentKind
    from syncr_solver.inputs import SolveInputs

CAREER_TASK: TaskId = UUID("f2f2f2f2-0000-4000-8000-000000000001")
FITNESS_TASK: TaskId = UUID("f2f2f2f2-0000-4000-8000-000000000002")

# The two Areas, pinned rather than minted per call. A caller that assembles this week TWICE -- once
# before a concession exists and once after -- compares figures keyed by Area, and a fresh identity
# per assembly would make the pair incomparable in a way that reads as a missing Area rather than as
# two different weeks.
CAREER_AREA: AreaId = UUID("f2f2f2f2-0000-4000-8000-00000000000a")
FITNESS_AREA: AreaId = UUID("f2f2f2f2-0000-4000-8000-00000000000b")

# The elastic routine, pinned for the same reason: a ``reduce_routine`` concession names the routine
# it shortens, so a routine minted per call would leave a stored concession targeting a routine the
# second assembly does not hold, and the fold would apply to nothing while every figure still looked
# plausible.
ELASTIC_SLEEP: UUID = UUID("f2f2f2f2-0000-4000-8000-00000000000c")


def a_week_every_kind_can_be_offered_in(**overrides: Any) -> WeekAssembler:
    """One assembly a concession of any of the four kinds applies to.

    ``overrides`` reach the assembler, which is what lets a caller swap one seam -- the concession
    repository, say, for a real one -- while keeping the week the offers were computed in.
    """
    career = an_area(area_id=CAREER_AREA, name="Career")
    fitness = an_area(area_id=FITNESS_AREA, name="Fitness", floor_hours=Decimal(5))
    # Half a step past the forty hours is what makes the shortfall the fixture's own ninety
    # minutes: three reducible nights at the sleep routine's give, which is what the fixture's
    # REDUCTIONS and LABEL describe.
    task = a_task(
        task_id=CAREER_TASK,
        area_id=career.id,
        estimate_minutes=40 * MINUTES_PER_HOUR + 30,
        deadline=at(10, day=3),
    )
    seams: dict[str, Any] = {
        "areas": FakeAreas([fitness, career]),
        "tasks": FakeTasks([task]),
        "routines": FakeRoutines([an_elastic_sleep()]),
        "preferences": FakePreferences([a_preference(owner=a_task_owner(task.id))]),
        "off_plan": FakeOffPlan([an_off_plan_period(interval=between(10, 24 * 4 + 24, day=3))]),
    }
    return an_assembler(**(seams | overrides))


def a_task_owner(task_id: TaskId) -> PreferenceOwner:
    """A preference attached to one task. The shared builders name an Area and a Habit only."""
    return PreferenceOwner(kind=PreferenceOwnerKind.TASK, id=task_id)


def an_elastic_sleep() -> Any:
    """The sleep routine with give in it, from the domain's own fixture."""
    return a_routine(
        routine_id=ELASTIC_SLEEP,
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
