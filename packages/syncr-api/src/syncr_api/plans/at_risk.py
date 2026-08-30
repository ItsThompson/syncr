"""Which tasks a verdict puts at risk. One rule, read by the backlog and by nothing else.

: a task is at risk **when and only when the verdict reports a ``deadline_capacity``
shortfall naming it**. The backlog computes no comparison of its own, and this module computes none
either: it reads a verdict the probe produced and decides which of the tenant's tasks each gap was
raised against. A second comparison of a deadline against a capacity is exactly how a task comes to
be at risk on one screen and fine on another.

**The gap is matched on three things, and each rules out a different false positive.**

*The Area and the deadline* are the pair the probe's demands were GROUPED by, so together they say
which demand this gap is about: another Area's gap at the same instant, or the same Area's gap at a
different one, is not this task's. :func:`syncr_api.plans.tradeoff_targets.due_at` states the same
pair over the solver's own eligible rows, for the same reason and against the same grouping.

*The title* is what the demand NAMED, and it is what narrows the group to the tasks that actually
owe the work: a task whose placements already cover its estimate before its own deadline produces
no demand at all, so it is absent from the names even though it shares the pair. Two tasks in one
Area sharing a title and a deadline are one demand and are both at risk, which is correct: the
demand is their sum.

**Only ``deadline_capacity``**. A packing failure is a fourth
shortfall kind that also names a task by title and carries a deadline, and it is deliberately not
read here: it says the capacity exists and could not be USED, which is a different statement from
the work not fitting before the instant it is due, and only one of the two is named here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.feasibility import ShortfallKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.feasibility import Shortfall, Verdict
    from syncr_domain.identifiers import TaskId


def tasks_at_risk(verdict: Verdict | None, tasks: Sequence[TaskRecord]) -> frozenset[TaskId]:
    """Which of ``tasks`` this verdict reports a deadline gap for.

    Empty for a week with no verdict, which is a week with no plan: nothing has been computed about
    it, so nothing about it is known to be at risk. Empty too for a verdict that found no gap.
    """
    if verdict is None:
        return frozenset()
    gaps = tuple(gap for gap in verdict.shortfalls if gap.kind is ShortfallKind.DEADLINE_CAPACITY)
    return frozenset(task.id for task in tasks for gap in gaps if _names(gap, task))


def _names(gap: Shortfall, task: TaskRecord) -> bool:
    """Whether this gap was raised against work this task owes."""
    return (
        gap.area_id == task.area_id and gap.deadline == task.deadline and task.title in gap.against
    )
