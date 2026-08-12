"""Task physics: the vocabulary, the two invariants that are arithmetic, and eligibility.

A task is the only kind of intent the user authors one instance of at a time, and it is the
kind the solver has the most freedom over. That freedom is what makes the physics
load-bearing: without a declared minimum chunk and a declared atomicity, fill placement puts
fifteen minutes of something that needs an hour to start into whatever gap it finds.

Four rules live here, and each of them is a computation rather than a policy, which is why
they are in the pure package rather than at the boundary:

| Rule | Function |
|---|---|
| T1, a minimum chunk fits inside the estimate | :func:`require_a_chunk_that_fits` |
| T3, remaining work, never negative | :func:`remaining_minutes` |
| T4, a completed task is not placed again | :func:`is_eligible_for_solving` |
| a task leaves the backlog by one door only | :func:`require_a_compatible_ending` |

**A task carries no preferred time.** Preferred times are a ``Preference``, whose owner is an
Area, a Habit, or a Task, so a task inherits its Area's windows unless it overrides them.
There is deliberately no field here that could carry one, and no function here that reads one.

**Nothing here nets a placement.** ``remaining_minutes`` is ``estimate - recorded``, which is
the figure the backlog reports and the figure T3 defines. The solver's
``EligibleTask.remaining_minutes`` nets immovable placements on top of it and the probe's
``DeadlineDemand.remaining_minutes`` nets every placement before a deadline: three quantities,
computed by whoever holds the placements. :func:`is_eligible_for_solving` therefore takes a
remaining figure rather than computing one, so the assembler can hand it its own netted number
and still ask this one question.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from syncr_domain.errors import DomainError
from syncr_domain.snap import SNAP_MINUTES


class TaskStatus(StrEnum):
    """Where a task is. Two of the three are endings, and nothing here returns a task to open."""

    OPEN = "open"
    COMPLETED = "completed"
    DROPPED = "dropped"


class Priority(StrEnum):
    """How much the objective prefers placing this task over another in the same Area."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# The two statuses a task can end in. A type rather than a runtime check, so a caller cannot
# ask to "end" a task by reopening it and there is no branch here answering for one that did.
type TaskEnding = Literal[TaskStatus.COMPLETED, TaskStatus.DROPPED]

# What capture assumes when the user states only a title and an Area. Each is derived from
# something already stated elsewhere rather than picked, because a default nobody can explain
# is a value every later reader has to guess the intent of.
#
# The estimate is two grid steps: the smallest estimate the default minimum chunk can divide,
# so a captured task is splittable in fact and not merely in flag.
DEFAULT_ESTIMATE_MINUTES: Final = 2 * SNAP_MINUTES
# The minimum chunk is one grid step, which is the smallest interval the week grid can draw. A
# larger default would invent a constraint the user did not state, which is the opposite of
# what T1 is for: the minimum chunk exists so the user can say "an hour or not at all".
DEFAULT_MIN_CHUNK_MINUTES: Final = SNAP_MINUTES
DEFAULT_PRIORITY: Final = Priority.NORMAL
# Splittable by default, because the physics that needs stating is atomicity: `Gym - Legs` is
# 90 minutes or nothing, and that is the claim worth making the user make.
DEFAULT_SPLITTABLE: Final = True
# A task accumulates recorded time from confirmed outcomes, so a captured one has none.
NO_RECORDED_MINUTES: Final = 0


class ChunkLargerThanEstimate(DomainError):
    """T1: a minimum chunk that does not fit inside the estimate."""


class TaskAlreadyEnded(DomainError):
    """A task that already left the backlog is being sent out through the other door."""


def default_min_chunk_minutes(estimate_minutes: int) -> int:
    """The minimum chunk a capture that stated an estimate but no chunk gets.

    Clamped down to the estimate, so a stated estimate smaller than one grid step cannot
    collide with an unstated default and produce a T1 rejection the caller did not cause.
    """
    return min(DEFAULT_MIN_CHUNK_MINUTES, estimate_minutes)


def require_a_chunk_that_fits(*, estimate_minutes: int, min_chunk_minutes: int) -> None:
    """T1: refuse a minimum chunk larger than the estimate it is a chunk of.

    A larger minimum is unsatisfiable rather than merely odd: the solver would have to place
    more minutes than the task has left in order to place any of it, so the task is silently
    unschedulable for as long as the pair stands.
    """
    if min_chunk_minutes <= estimate_minutes:
        return
    raise ChunkLargerThanEstimate(
        f"a minimum chunk of {min_chunk_minutes} minutes does not fit inside an estimate of "
        f"{estimate_minutes} minutes, so no placement could ever satisfy both"
    )


def remaining_minutes(*, estimate_minutes: int, recorded_minutes: int) -> int:
    """T3: the work left on a task, which is never negative.

    Clamped rather than constrained at the column, because recording more time than was
    estimated is an ordinary thing to do: an estimate is a guess and an outcome is a fact.
    What the clamp keeps true is that no caller ever multiplies, sums, or renders a negative
    quantity of work.
    """
    return max(0, estimate_minutes - recorded_minutes)


def is_eligible_for_solving(*, status: TaskStatus, remaining_minutes: int) -> bool:
    """T4: whether the solver may place this task at all.

    The remaining figure is passed in rather than computed, because which placements it nets
    depends on who is asking: the backlog reports T3's figure, and the week assembler nets
    immovable placements out of it first. Both ask this same question of the answer.

    Completing or dropping a task therefore takes it out of eligibility on the next assembly
    with no separate signal, and ``recorded_minutes`` is untouched by either, so the time
    already spent survives in reports.
    """
    return status is TaskStatus.OPEN and remaining_minutes > 0


def require_a_compatible_ending(*, current: TaskStatus, ending: TaskEnding) -> None:
    """Refuse ending a task the opposite way to how it already ended.

    Completed and dropped are both endings and they say opposite things: one is work that
    happened and survives in reports, the other is work that will not happen. Ending an open
    task either way is allowed, and ending a task the way it already ended is allowed and
    changes nothing, which is what makes a retried request safe. Crossing between the two is
    refused, because it would either erase a completion a report already counted or claim one
    that never occurred.
    """
    if current is TaskStatus.OPEN or current is ending:
        return
    raise TaskAlreadyEnded(
        f"this task is already {current.value}, so it cannot be recorded as {ending.value}"
    )
