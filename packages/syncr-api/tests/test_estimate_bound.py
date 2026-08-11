"""What the estimate bound is about, driven through the arithmetic that reads it.

``ESTIMATE_MINUTES_MAX`` is the nominal week's own length, so what a value above it would mean is
a statement about a week's capacity rather than about a column. The three steps that reach that
statement are composed here rather than described: ``task_demands`` computes what a task still
owes before its deadline, the probe compares that against the capacity its Area has before the
instant, and ``tasks_at_risk`` marks every task a deadline gap names.

**The week is the most generous one a nominal span can be.** Nothing is occupied, nothing has
elapsed, and the deadline falls at the span's end, so the whole week is capacity this one task may
claim. A demand this week refuses is refused by every nominal week, because
`discretionary_intervals` only subtracts from the span and no discount can raise a capacity: a
frame, an anchor, or a Wednesday can only take capacity away.

**Both halves of the recorded reason are driven, and they are about different quantities.** The
splittable half is about the total, so it is measured against the week's capacity. The atomic half
is about the longest contiguous run, because an atomic task is placed whole, and an empty nominal
week is one run of exactly the bound. Neither half branches on ``splittable`` and a case says so.

**A task above the bound is built as a record rather than captured**, because the bound is what
stops such a task existing: the route refuses it, and this suite is about the reading the refusal
prevents.

The fall-back week is driven too, and it holds the minute above the bound in both quantities: a
week whose clocks go back is an hour longer than a nominal one, so it is the one span the
arithmetic alone does not refuse. That is why every claim in the recorded reason names the
**nominal** week, and why a case reads that scoping off the docstring rather than trusting it.

**The remedy the reason recommends is driven as well as the refusal.** A demand is grouped per
deadline and Area, so two parts of one Project sharing both are one demand naming both, and the
answers separate once either component of that key does.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syncr_api.plans.at_risk import tasks_at_risk
from syncr_api.plans.demand import deadline_demands, task_demands
from syncr_api.plans.multipliers import DurationMultipliers
from syncr_api.plans.netting import PlacedTime
from syncr_api.tasks import config
from syncr_api.tasks.config import ESTIMATE_MINUTES_MAX, MINUTES_IN_AN_HOUR
from syncr_domain.discretionary import discretionary_intervals
from syncr_domain.feasibility import ProbeInputs, ShortfallKind, probe
from syncr_domain.fixtures.dst_weeks import FALL_BACK
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.tasks import TaskStatus
from tests.test_at_risk_tasks import CAREER, FITNESS, a_task

if TYPE_CHECKING:
    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.identifiers import AreaId

# Monday to Monday in UTC, so the span is a nominal week and no transition has to be reasoned
# about. `FALL_BACK` owns the week that is longer than one.
NOMINAL_WEEK = Interval(datetime(2026, 2, 9, tzinfo=UTC), datetime(2026, 2, 16, tzinfo=UTC))

# A week after the span ends, for the pair of cases about two parts of one Project. A deadline
# beyond the week is a demand like any other: what a week's capacity can reach is the probe's
# question, not the demand's.
A_WEEK_LATER = datetime(2026, 2, 23, tzinfo=UTC)

A_TITLE = "Rewrite the thesis"
ANOTHER_TITLE = "Rewrite the appendix"


def a_task_owing(
    minutes: int,
    *,
    due: datetime | None,
    title: str = A_TITLE,
    area_id: AreaId = CAREER,
    **changes: object,
) -> TaskRecord:
    """One open task owing ``minutes`` by ``due``, or by nothing at all.

    Every dated case passes the instant its own week ends, because a deadline inside the week clips
    the capacity before it and a deadline behind the week has none at all: both are a second reason
    for a figure to be small, and these cases are about the whole week's capacity.
    """
    return a_task(
        title=title,
        area_id=area_id,
        estimate_minutes=minutes,
        deadline=due,
        status=TaskStatus.OPEN,
        **changes,
    )


def free(span: Interval) -> IntervalSet:
    """The discretionary set of a week with nothing at all in it.

    The same function the probe derives its capacity from, so a run measured here is a run a
    placement would be offered.
    """
    empty = IntervalSet()
    return discretionary_intervals(
        span, frame=empty, anchors=empty, absolute_forbidden=empty, off_plan=empty
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

    Nothing has to fit before anything, so such a task raises no demand and no gap names it. That is
    the whole of what "while it carries a deadline" buys the sentence.
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


def test_an_empty_nominal_week_is_one_run_of_the_bound_and_a_fall_back_week_is_an_hour_longer() -> (
    None
):
    """The quantity the atomic half of the reason is about: the longest contiguous run a week has.

    An atomic task is placed whole, so what refuses one above the bound is the length of the longest
    run, not the total. An empty nominal week is a single run and it is exactly the bound, which is
    the equality the reason rests on. The fall-back week is the counter-example in the same shape.
    """
    nominal = free(NOMINAL_WEEK)
    longer = free(FALL_BACK.span)

    assert [run.total_minutes() for run in nominal] == [ESTIMATE_MINUTES_MAX]
    assert [run.total_minutes() for run in longer] == [ESTIMATE_MINUTES_MAX + MINUTES_IN_AN_HOUR]


def test_an_atomic_task_reads_exactly_as_a_splittable_one_does() -> None:
    """The bound does not branch on atomicity, so neither does the reading it feeds.

    Both halves of the recorded reason are about the same figure, and this is the case that says the
    figure is one figure: the demand, the gap and the at-risk answer are identical for a task the
    solver may divide and one it may not.
    """
    atomic = a_task_owing(ESTIMATE_MINUTES_MAX + 1, due=NOMINAL_WEEK.end, splittable=False)
    divisible = a_task_owing(ESTIMATE_MINUTES_MAX + 1, due=NOMINAL_WEEK.end)

    atomic_verdict = probe(a_week_owing(atomic, span=NOMINAL_WEEK))
    divisible_verdict = probe(a_week_owing(divisible, span=NOMINAL_WEEK))

    (atomic_gap,) = atomic_verdict.shortfalls
    (divisible_gap,) = divisible_verdict.shortfalls
    assert atomic_gap == divisible_gap
    assert tasks_at_risk(atomic_verdict, [atomic]) == {atomic.id}
    assert tasks_at_risk(divisible_verdict, [divisible]) == {divisible.id}


def test_the_answers_separate_once_the_two_parts_areas_do() -> None:
    """The other half of the grouping key, on one shared deadline.

    A demand is grouped per deadline AND Area, so two parts filed in different Areas are two demands
    at the same instant. Each is then checked against the capacity its own Area may claim after the
    other's, so one of the two carries the gap and the other is told the week has room.
    """
    career = a_task_owing(ESTIMATE_MINUTES_MAX, due=NOMINAL_WEEK.end)
    fitness = a_task_owing(
        ESTIMATE_MINUTES_MAX, due=NOMINAL_WEEK.end, title=ANOTHER_TITLE, area_id=FITNESS
    )
    inputs = a_week_owing(career, fitness, span=NOMINAL_WEEK)

    verdict = probe(inputs)

    # Two demands at one instant, each naming its own part. Sorted, because `deadline_demands`
    # breaks the tie between two Areas at one deadline on the Area id, so which of the two the
    # probe serves first is a property of the fixture's identifiers rather than of the rule.
    assert sorted(demand.labels for demand in inputs.deadline_demands) == [
        (ANOTHER_TITLE,),
        (A_TITLE,),
    ]
    (gap,) = verdict.shortfalls
    assert gap.minutes == ESTIMATE_MINUTES_MAX
    named = {part.id for part in (career, fitness) if part.title in gap.against}
    assert len(named) == 1
    assert tasks_at_risk(verdict, [career, fitness]) == named


def _stated() -> str:
    """The bound's own statement as one line.

    Read with its line wrapping collapsed, because a claim is a claim wherever the wrap falls: the
    first version of these assertions passed on "at risk" and failed on "at\nrisk" after a reflow.
    """
    return " ".join((config.__doc__ or "").split())


def test_the_recorded_reason_names_the_reading_it_claims() -> None:
    """The citations beside the bound have to resolve, or the reason rots into a story.

    A reason naming a reader or a shortfall kind that no longer exists is worse than no reason: the
    next ticket widening the bound reads a mechanism it cannot check. Each citation is asserted
    against the symbol it names, so a rename anywhere in it reddens rather than passing.
    """
    stated = _stated()

    assert f"{tasks_at_risk.__module__}.{tasks_at_risk.__qualname__}" in stated
    assert ShortfallKind.DEADLINE_CAPACITY.name in stated
    assert "at risk" in stated


# What a universal claim in that docstring looks like: a quantifier, then within a few words the
# noun it quantifies. The fall-back week falsifies any such claim that does not name the nominal
# week, which is why the scope word has to be inside the same window rather than somewhere in the
# paragraph. `never` and its relatives carry the same claim with no noun to scope, so they have no
# place in a statement about one week's length.
_A_QUANTIFIER = re.compile(r"\b(?:every|no|any|each|all)\b", re.IGNORECASE)
_QUANTIFIED = ("week", "verdict")
_UNSCOPED_WORDS = ("never", "forever", "always")
_WINDOW = 6


def _unscoped_claims(stated: str) -> list[str]:
    """Each quantified claim about a week or a verdict that does not name the nominal one."""
    words = stated.split()
    found: list[str] = []
    for index, word in enumerate(words):
        if not _A_QUANTIFIER.fullmatch(word.strip("*,.:`'")):
            continue
        window = " ".join(words[index : index + _WINDOW + 1])
        spelled = window.lower()
        if any(noun in spelled for noun in _QUANTIFIED) and "nominal" not in spelled:
            found.append(window)
    return found


def test_no_claim_in_the_recorded_reason_is_a_universal_the_fall_back_week_falsifies() -> None:
    """Three rounds of review found the same defect here, each time at a different clause.

    A claim that every week, or no week, or every verdict does something is false for a week whose
    clocks go back, and each of the three shipped that claim in a different spelling. So this reads
    the shape rather than the spellings: a quantifier near "week" or "verdict" has to name the
    nominal one, and a true rewording that scopes itself in the same breath passes.
    """
    stated = _stated()

    assert _unscoped_claims(stated) == []
    assert [word for word in _UNSCOPED_WORDS if re.search(rf"\b{word}\b", stated, re.I)] == []
