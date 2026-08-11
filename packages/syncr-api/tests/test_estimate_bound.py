"""What the estimate bound is about, driven through the arithmetic that reads it.

``ESTIMATE_MINUTES_MAX`` is the nominal week's own length, so what a value above it would mean is
a statement about a week's capacity rather than about a column. The three steps that reach that
statement are composed here rather than described: ``task_demands`` computes what a task still
owes before its deadline, the probe compares that against the capacity its Area has before the
instant, and ``tasks_at_risk`` marks every task a deadline gap names.

**The week is the most generous one a nominal span can be.** Nothing is occupied, nothing has
elapsed, and the deadline falls at the span's end, so the whole week is capacity this one task may
claim. A demand this week refuses is refused by every nominal week, because a frame, an anchor, or
a Wednesday only takes capacity away.

**A task above the bound is built as a record rather than captured**, because the bound is what
stops such a task existing: the route refuses it, and this suite is about the reading the refusal
prevents.

The fall-back week is driven too, and it holds the minute above the bound: a week whose clocks go
back is an hour longer than a nominal one, so it is the one span the arithmetic alone does not
refuse. That is why the recorded reason claims a **nominal** week's verdict rather than every
week's, and the case after it pins the escape at exactly the hour the week gains.

**The remedy the reason recommends is driven as well as the refusal.** A demand is grouped per
deadline and Area, so two parts of one Project sharing one deadline are one demand naming both, and
the answers separate once their deadlines do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syncr_api.plans.at_risk import tasks_at_risk
from syncr_api.plans.demand import deadline_demands, task_demands
from syncr_api.plans.multipliers import DurationMultipliers
from syncr_api.plans.netting import PlacedTime
from syncr_api.tasks import config
from syncr_api.tasks.config import ESTIMATE_MINUTES_MAX, MINUTES_IN_AN_HOUR
from syncr_domain.feasibility import ProbeInputs, ShortfallKind, probe
from syncr_domain.fixtures.dst_weeks import FALL_BACK
from syncr_domain.intervals import Interval
from syncr_domain.tasks import TaskStatus
from tests.test_at_risk_tasks import CAREER, a_task

if TYPE_CHECKING:
    from syncr_api.tasks.records import TaskRecord

# Monday to Monday in UTC, so the span is a nominal week and no transition has to be reasoned
# about. `FALL_BACK` owns the week that is longer than one.
NOMINAL_WEEK = Interval(datetime(2026, 2, 9, tzinfo=UTC), datetime(2026, 2, 16, tzinfo=UTC))

# A week after the span ends, for the pair of cases about two parts of one Project. A deadline
# beyond the week is a demand like any other: what a week's capacity can reach is the probe's
# question, not the demand's.
A_WEEK_LATER = datetime(2026, 2, 23, tzinfo=UTC)

A_TITLE = "Rewrite the thesis"
ANOTHER_TITLE = "Rewrite the appendix"


def a_task_owing(minutes: int, *, due: datetime | None, title: str = A_TITLE) -> TaskRecord:
    """One open task owing ``minutes`` by ``due``, or by nothing at all.

    Every dated case passes the instant its own week ends, because a deadline inside the week clips
    the capacity before it and a deadline behind the week has none at all: both are a second reason
    for a figure to be small, and these cases are about the whole week's capacity.
    """
    return a_task(
        title=title,
        area_id=CAREER,
        estimate_minutes=minutes,
        deadline=due,
        status=TaskStatus.OPEN,
    )


def a_week_owing(*tasks: TaskRecord, span: Interval) -> ProbeInputs:
    """A week with nothing in it at all, owing whatever those tasks owe before their deadlines.

    ``now`` is the span's start, so no capacity has elapsed. The demands are computed by the
    assembler's own functions rather than stated, so an estimate reaches the probe the way a stored
    task's would, and two tasks group the way two stored ones would.
    """
    demands = task_demands(
        tasks, placed=PlacedTime([], now=span.start), multipliers=DurationMultipliers.of(None)
    )
    return ProbeInputs(
        span=span,
        now=span.start,
        computed_at=span.start,
        input_version=1,
        deadline_demands=deadline_demands(demands),
    )


def test_a_task_the_size_of_the_bound_fits_the_week_the_bound_is_the_length_of() -> None:
    task = a_task_owing(ESTIMATE_MINUTES_MAX, due=NOMINAL_WEEK.end)
    inputs = a_week_owing(task, span=NOMINAL_WEEK)

    verdict = probe(inputs)

    # What the probe was asked, before what it answered. A case that reports no gap because its
    # demand never reached the probe passes for the wrong reason, so a case asserting an absence
    # states the demand that produced it.
    assert [demand.remaining_minutes for demand in inputs.deadline_demands] == [
        ESTIMATE_MINUTES_MAX
    ]
    # The equality the bound exists to state: a nominal week with nothing in it is exactly this
    # many minutes, so a task at the bound is the largest one a week can hold.
    assert verdict.discretionary_minutes == ESTIMATE_MINUTES_MAX
    assert verdict.shortfalls == ()
    assert tasks_at_risk(verdict, [task]) == frozenset()


def test_a_task_a_minute_above_the_bound_is_at_risk_in_a_week_with_nothing_in_it() -> None:
    """The reading the bound prevents, measured: the gap is the minute the week cannot hold."""
    task = a_task_owing(ESTIMATE_MINUTES_MAX + 1, due=NOMINAL_WEEK.end)

    verdict = probe(a_week_owing(task, span=NOMINAL_WEEK))

    (gap,) = verdict.shortfalls
    assert gap.kind is ShortfallKind.DEADLINE_CAPACITY
    assert gap.minutes == 1
    assert gap.against == (A_TITLE,)
    assert tasks_at_risk(verdict, [task]) == {task.id}


def test_the_hour_a_fall_back_week_gains_is_the_one_span_that_holds_the_minute_above_it() -> None:
    """The limit of the claim, driven rather than left for a reader to find.

    A week whose clocks go back has an hour more span than a nominal one, and with nothing in it
    that hour is capacity. So the arithmetic alone does not refuse this task in this week: what
    refuses it in a real one is that a week's capacity is a fraction of its span.
    """
    task = a_task_owing(ESTIMATE_MINUTES_MAX + 1, due=FALL_BACK.span.end)
    inputs = a_week_owing(task, span=FALL_BACK.span)

    verdict = probe(inputs)

    assert [demand.remaining_minutes for demand in inputs.deadline_demands] == [
        ESTIMATE_MINUTES_MAX + 1
    ]
    assert verdict.discretionary_minutes == ESTIMATE_MINUTES_MAX + MINUTES_IN_AN_HOUR
    assert verdict.shortfalls == ()
    assert tasks_at_risk(verdict, [task]) == frozenset()


def test_the_fall_back_week_refuses_the_minute_above_the_hour_it_gains() -> None:
    """The width of that escape, so it is one hour rather than an unmeasured amount.

    Without this, a change that gave every week a second spare hour would redden one case here and
    leave the escape looking the same size as before.
    """
    owed = ESTIMATE_MINUTES_MAX + MINUTES_IN_AN_HOUR + 1
    task = a_task_owing(owed, due=FALL_BACK.span.end)

    verdict = probe(a_week_owing(task, span=FALL_BACK.span))

    (gap,) = verdict.shortfalls
    assert gap.kind is ShortfallKind.DEADLINE_CAPACITY
    assert gap.minutes == 1
    assert tasks_at_risk(verdict, [task]) == {task.id}


def test_a_task_above_the_bound_with_no_deadline_owes_nothing_and_is_never_at_risk() -> None:
    """The clause the recorded reason carries, driven: the reading needs a deadline to exist.

    Nothing has to fit before anything, so such a task raises no demand and no gap names it. It is
    the input class the at-risk half of the reason says nothing about.
    """
    task = a_task_owing(ESTIMATE_MINUTES_MAX + 1, due=None)
    inputs = a_week_owing(task, span=NOMINAL_WEEK)

    verdict = probe(inputs)

    assert inputs.deadline_demands == ()
    assert verdict.shortfalls == ()
    assert tasks_at_risk(verdict, [task]) == frozenset()


def test_two_parts_of_one_project_sharing_a_deadline_are_one_demand_and_both_at_risk() -> None:
    """The remedy's limit: splitting the work does not split the answer while one deadline holds.

    Two tasks in one Area due at one instant compete for the same capacity, so the probe reads them
    as one demand and the gap it raises names both.
    """
    thesis = a_task_owing(ESTIMATE_MINUTES_MAX, due=NOMINAL_WEEK.end)
    appendix = a_task_owing(ESTIMATE_MINUTES_MAX, due=NOMINAL_WEEK.end, title=ANOTHER_TITLE)
    inputs = a_week_owing(thesis, appendix, span=NOMINAL_WEEK)

    verdict = probe(inputs)

    (demand,) = inputs.deadline_demands
    assert demand.remaining_minutes == 2 * ESTIMATE_MINUTES_MAX
    assert demand.labels == (ANOTHER_TITLE, A_TITLE)
    (gap,) = verdict.shortfalls
    assert gap.minutes == ESTIMATE_MINUTES_MAX
    assert gap.against == (ANOTHER_TITLE, A_TITLE)
    assert tasks_at_risk(verdict, [thesis, appendix]) == {thesis.id, appendix.id}


def test_the_answers_separate_once_the_two_parts_deadlines_do() -> None:
    """And the remedy arrives with the second deadline, which is what the recorded reason says.

    Two demands rather than one, and the earlier deadline is told the whole week is available to it.
    The later one competes with what the earlier already claimed, so it carries the whole gap and it
    alone reads as at risk.
    """
    thesis = a_task_owing(ESTIMATE_MINUTES_MAX, due=NOMINAL_WEEK.end)
    appendix = a_task_owing(ESTIMATE_MINUTES_MAX, due=A_WEEK_LATER, title=ANOTHER_TITLE)
    inputs = a_week_owing(thesis, appendix, span=NOMINAL_WEEK)

    verdict = probe(inputs)

    assert [demand.labels for demand in inputs.deadline_demands] == [(A_TITLE,), (ANOTHER_TITLE,)]
    (gap,) = verdict.shortfalls
    assert gap.minutes == ESTIMATE_MINUTES_MAX
    assert gap.against == (ANOTHER_TITLE,)
    assert tasks_at_risk(verdict, [thesis, appendix]) == {appendix.id}


def test_the_recorded_reason_names_the_reading_it_claims() -> None:
    """The citations beside the bound have to resolve, or the reason rots into a story.

    A reason naming a reader or a shortfall kind that no longer exists is worse than no reason: the
    next ticket widening the bound reads a mechanism it cannot check. Each citation is asserted
    against the symbol it names, so a rename anywhere in it reddens rather than passing.
    """
    stated = config.__doc__ or ""

    assert f"{tasks_at_risk.__module__}.{tasks_at_risk.__qualname__}" in stated
    assert ShortfallKind.DEADLINE_CAPACITY.name in stated
    assert "at risk" in stated
    # The claim is about a nominal week, and the fall-back case above is the counter-example that
    # makes the wider one false. The narrower spelling can be reworded; the universal cannot return.
    assert "every verdict" not in stated
