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

The fall-back week is driven too, and it passes. A week whose clocks go back is an hour longer
than a nominal one, so it is the one span where the arithmetic alone holds the minute above the
bound, and the reason recorded beside the constant is worded to claim no more than that.
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

A_TITLE = "Rewrite the thesis"


def a_task_owing(minutes: int, *, due: datetime) -> TaskRecord:
    """One open task owing ``minutes`` by ``due``.

    Every case passes the instant its own week ends, because a deadline inside the week clips the
    capacity before it and a deadline behind the week has none at all: both are a second reason
    for a figure to be small, and these cases are about the whole week's capacity.
    """
    return a_task(
        title=A_TITLE,
        area_id=CAREER,
        estimate_minutes=minutes,
        deadline=due,
        status=TaskStatus.OPEN,
    )


def a_week_owing(task: TaskRecord, *, span: Interval) -> ProbeInputs:
    """A week with nothing in it at all, owing whatever that task owes before its deadline.

    ``now`` is the span's start, so no capacity has elapsed. The demand is computed by the
    assembler's own function rather than stated, so the estimate reaches the probe the way a
    stored task's would.
    """
    demands = task_demands(
        [task], placed=PlacedTime([], now=span.start), multipliers=DurationMultipliers.of(None)
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
    # demand never reached the probe passes for the wrong reason, and the two cases here that
    # assert an absence are the two that reading cannot tell apart.
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


def test_the_recorded_reason_names_the_reading_it_claims() -> None:
    """The citation beside the bound has to resolve, or the reason rots into a story.

    A reason naming a reader that no longer exists is worse than no reason: the next ticket
    widening the bound reads a mechanism it cannot check. Importing the reader is half the check
    and naming it in the statement is the other half.
    """
    stated = config.__doc__ or ""

    assert tasks_at_risk.__name__ in stated
    assert "at risk" in stated
