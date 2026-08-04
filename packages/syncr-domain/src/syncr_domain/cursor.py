"""The rotation cursor: a projection of the outcome log, and therefore read-only.

``Gym`` is on ``Legs`` *because* ``Chest & Back`` was confirmed complete. The cursor is not a
stored field, and four consequences follow from that one choice:

| Consequence | Detail |
|---|---|
| There is no "set cursor" control | Editing derived state desyncs it from the log |
| A wrong cursor means a wrong confirmation | The user fixes the day on Today, and this re-derives |
| Overriding one occurrence is a rebind | A rebind is a pin, which already exists |
| Desync is impossible by construction | The cursor has no independent storage to drift from |

**The cursor is a count, and that is what makes it order-free.** It advances once per
confirmed completion, so the index is the number of them modulo the variant count. Addition
commutes, so permuting the log cannot move it, and there is no accumulator whose intermediate
state a caller could observe. That is the property X8 asserts, and it holds by construction
rather than by care.

**No date arithmetic happens here.** The count reads a state and a confirmation, never a
calendar, so a daylight-saving transition, a year boundary, and a tenant who changes zone are
all invisible to it. The one instant this module reads is the most recent confirmation, and it
is read to *name* the provenance rather than to compute the index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.errors import DomainError
from syncr_domain.habits import BindingSource

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_domain.habits import Habit
    from syncr_domain.intervals import Instant
    from syncr_domain.outcomes import HabitOutcome


class NoRotationCursor(DomainError):
    """A cursor was asked for on a habit that does not rotate."""


@dataclass(frozen=True, slots=True)
class CursorReading:
    """Where a rotation habit's cursor sits, and what it rests on.

    Every field is a function of the log, so two readings of one log are equal whatever order
    the outcomes arrived in. ``statement`` is what an interface renders beside the variant,
    because a value the user cannot change has to say why it is what it is.
    """

    index: int
    variant: str
    confirmed_completions: int
    previous_variant: str | None
    advanced_at: Instant | None
    statement: str


def derive_cursor(habit: Habit, outcomes: Sequence[HabitOutcome]) -> int:
    """The index into ``habit.variants`` this outcome log puts the habit on.

    Advances once per confirmed completion. A skip does not advance, which is the point:
    missing Tuesday must not skip a muscle group. An unconfirmed day does not advance either,
    because the user has not yet said what happened.

    Raises :class:`NoRotationCursor` for any other binding source. A fixed habit repeats one
    content and a queue habit draws from the backlog, so neither has an index to hold, and
    answering zero would be a cursor that reads as meaningful.
    """
    require_rotation(habit)
    return _completions(habit, outcomes) % len(habit.variants)


def cursor_reading(habit: Habit, outcomes: Sequence[HabitOutcome]) -> CursorReading | None:
    """The cursor and its provenance, or ``None`` for a habit that does not rotate.

    ``None`` rather than a rejection, because a caller rendering a list of habits asks this of
    every one of them and a fixed habit displaying no cursor at all is the correct answer
    rather than an error.
    """
    if not habit.rotates:
        return None
    completions = _completions(habit, outcomes)
    index = completions % len(habit.variants)
    variant = habit.variants[index]
    previous = habit.variants[(index - 1) % len(habit.variants)] if completions else None
    return CursorReading(
        index=index,
        variant=variant,
        confirmed_completions=completions,
        previous_variant=previous,
        advanced_at=_last_confirmation(habit, outcomes),
        statement=_statement(variant, previous),
    )


def require_rotation(habit: Habit) -> Habit:
    """``habit`` unchanged, or a rejection naming why it holds no cursor."""
    if habit.rotates:
        return habit
    raise NoRotationCursor(
        f"a {habit.binding_source.value!r} habit holds no rotation cursor: only "
        f"{BindingSource.ROTATION.value!r} binds content from an ordered variant list"
    )


def _completions(habit: Habit, outcomes: Iterable[HabitOutcome]) -> int:
    return sum(1 for outcome in _of(habit, outcomes) if outcome.is_confirmed_completion)


def _last_confirmation(habit: Habit, outcomes: Iterable[HabitOutcome]) -> Instant | None:
    """When the most recent confirmed completion was confirmed.

    Ordered by the confirmation instant and broken by the occurrence's own scheduled instant
    and key, so two rows confirmed in one call still resolve to one answer and the whole
    reading stays permutation-invariant.
    """
    confirmed = [
        (outcome.confirmed_at, outcome.occurred_at, outcome.occurrence_key)
        for outcome in _of(habit, outcomes)
        if outcome.is_confirmed_completion and outcome.confirmed_at is not None
    ]
    if not confirmed:
        return None
    return max(confirmed)[0]


def _of(habit: Habit, outcomes: Iterable[HabitOutcome]) -> Iterable[HabitOutcome]:
    """The outcomes whose binding names this habit. Everything else in the log is not ours."""
    return (outcome for outcome in outcomes if outcome.habit_id == habit.id)


def _statement(variant: str, previous: str | None) -> str:
    if previous is None:
        return (
            f"On {variant}, the first variant: no completion has been confirmed yet. Derived "
            "from the outcome log, so there is no control to set it."
        )
    return (
        f"On {variant} because {previous} was confirmed complete. Derived from the outcome "
        "log, so there is no control to set it: correct the day on Today and this re-derives."
    )
