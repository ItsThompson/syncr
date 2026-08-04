"""The two task quantities, computed side by side so neither can be read as the other.

Both answer "how much of this task is left" and they net different placement sets, for
opposite reasons. They are in one module deliberately: the defect that has been found three
times is a reader taking one of a pair for the other, and the strongest structural answer is
that a reader cannot open one without seeing the other.

```
                       eligible_tasks()             task_demands()
reader                 the SOLVER                   the PROBE, via for_probe()
nets                   IMMOVABLE placements only    EVERY placement
deadline-scoped         no. A whole-task figure     YES. Only what falls before it counts
max() correction        no                          YES, over recorded and past-placed
```

**If the solver read the probe's number:** a 4h task with 2h placed unpinned yields 2h, the
solver places 2h, the task is scheduled at half its size, and nothing reports a shortfall
because both sides agree. **If the probe read the solver's number:** its free capacity
subtracts that 2h block while its demand does not, so it reports a shortfall the week does not
have.

The probe's figure is not derivable from the solver's, and that is why the assembler computes
it rather than the projection deriving it: it needs the estimate, the recorded minutes, and the
placed intervals split before and after each deadline, and the first two appear nowhere on a
solve input.

Both start from the SAME corrected estimate. A multiplier applied to one and not the other
would be a third way for the pair to disagree, on top of the two differences that are
deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingRef
from syncr_domain.intervals import as_instant
from syncr_domain.tasks import is_eligible_for_solving, remaining_minutes
from syncr_solver.inputs import DeadlineDemand, EligibleTask

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.plans.multipliers import DurationMultipliers
    from syncr_api.plans.netting import PlacedTime
    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.identifiers import AreaId, TaskId
    from syncr_domain.intervals import Instant


@dataclass(frozen=True, slots=True)
class TaskDemand:
    """One task's demand before its own deadline: the probe's quantity, before grouping.

    Kept per task through the adjustment fold, because a concession is approved against a task
    and the demand the probe reads is per Area and deadline. Grouping is the last step and it
    changes no figure.
    """

    task_id: TaskId
    deadline: Instant
    area_id: AreaId
    title: str
    remaining_minutes: int


def eligible_tasks(
    tasks: Sequence[TaskRecord], *, placed: PlacedTime, multipliers: DurationMultipliers
) -> tuple[EligibleTask, ...]:
    """The tasks the solver may place, and how much of each is left to place.

    Eligibility is asked of the NETTED figure rather than of the backlog's own, so a task whose
    remaining work is entirely covered by past blocks and pins is not offered to the solver
    again. Order follows the backlog's, which is oldest first.
    """
    resolved: list[EligibleTask] = []
    for task in tasks:
        remaining = _solver_remaining_minutes(task, placed=placed, multipliers=multipliers)
        if not is_eligible_for_solving(status=task.status, remaining_minutes=remaining):
            continue
        resolved.append(
            EligibleTask(
                binding=BindingRef.for_task(task.id),
                remaining_minutes=remaining,
                deadline=None if task.deadline is None else as_instant(task.deadline),
                priority=task.priority,
                min_chunk_minutes=task.min_chunk_minutes,
                splittable=task.splittable,
                area_id=task.area_id,
                title=task.title,
            )
        )
    return tuple(resolved)


def task_demands(
    tasks: Sequence[TaskRecord], *, placed: PlacedTime, multipliers: DurationMultipliers
) -> tuple[TaskDemand, ...]:
    """What each deadline-bearing task still needs before its own deadline.

    A task with no deadline has no demand: nothing has to fit before anything. A task whose
    placements already cover its corrected estimate has none either, which is the whole point
    of netting: making progress must never manufacture a shortfall.

    **A deadline outside the week still produces a demand, in both directions.** A task due next
    month yields one at that instant, and a task due last Tuesday yields one too, which is correct
    because the work is overdue rather than excused. What a consumer does with a deadline the week's
    capacity window does not reach is the consumer's rule: the probe clips its capacity to the span
    and to ``now``, so a deadline in the past yields zero capacity and its whole demand is the
    shortfall.
    """
    demands: list[TaskDemand] = []
    for task in tasks:
        if task.deadline is None or not task.is_eligible_for_solving():
            continue
        deadline = as_instant(task.deadline)
        remaining = _probe_remaining_minutes(
            task, deadline=deadline, placed=placed, multipliers=multipliers
        )
        if remaining <= 0:
            continue
        demands.append(
            TaskDemand(
                task_id=task.id,
                deadline=deadline,
                area_id=task.area_id,
                title=task.title,
                remaining_minutes=remaining,
            )
        )
    return tuple(demands)


def deadline_demands(demands: Sequence[TaskDemand]) -> tuple[DeadlineDemand, ...]:
    """The per-task demands grouped per deadline and Area, earliest first.

    One demand per pair, because the probe compares a demand against the capacity that Area has
    before that instant: two tasks due at one moment in one Area compete for the same capacity,
    and two demands would each be checked against the whole of it.
    """
    grouped: dict[tuple[Instant, AreaId], list[TaskDemand]] = {}
    for demand in demands:
        grouped.setdefault((demand.deadline, demand.area_id), []).append(demand)
    return tuple(
        DeadlineDemand(
            deadline=deadline,
            area_id=area_id,
            remaining_minutes=sum(demand.remaining_minutes for demand in members),
            labels=tuple(sorted(demand.title for demand in members)),
        )
        for (deadline, area_id), members in sorted(grouped.items(), key=_demand_order)
    )


def _solver_remaining_minutes(
    task: TaskRecord, *, placed: PlacedTime, multipliers: DurationMultipliers
) -> int:
    """The corrected estimate less recorded minutes less IMMOVABLE placements. Never negative.

    An unpinned future block is deliberately not netted. The solver discards and re-places
    those, so netting them would leave the task permanently scheduled at part of its size,
    stably and with nothing reporting it.
    """
    backlog = remaining_minutes(
        estimate_minutes=multipliers.scale_estimate(task.estimate_minutes, area_id=task.area_id),
        recorded_minutes=task.recorded_minutes,
    )
    return max(0, backlog - placed.immovable_minutes_of_task(task.id))


def _probe_remaining_minutes(
    task: TaskRecord,
    *,
    deadline: Instant,
    placed: PlacedTime,
    multipliers: DurationMultipliers,
) -> int:
    """The corrected estimate less everything attributed to the task before ``deadline``.

    The ``max()`` is what stops a past block being counted twice. Before the day is confirmed
    the block carries the estimate and nothing is recorded; after it is confirmed
    ``recorded_minutes`` carries the truth, which may be higher because the block ran long or
    lower because it was partial, and the greater of the two is the honest figure.

    A future placement is added rather than compared, because it is scheduled work that no
    outcome can have recorded yet.
    """
    corrected = multipliers.scale_estimate(task.estimate_minutes, area_id=task.area_id)
    attributed = placed.attributed_to_task_before(task.id, deadline)
    return max(0, corrected - (max(task.recorded_minutes, attributed.past) + attributed.future))


def _demand_order(
    entry: tuple[tuple[Instant, AreaId], Sequence[TaskDemand]],
) -> tuple[Instant, str]:
    """Earliest deadline first, then the Area, so two assemblies emit one order."""
    (deadline, area_id), _ = entry
    return (deadline, str(area_id))
