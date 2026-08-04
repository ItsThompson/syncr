"""Expanding a habit's cadence into the occurrences one week holds.

A habit answers *when and how often*; this answers *how many, this week, and what each one
holds*. Three readings of stored state meet here, and each is already implemented in the pure
package rather than a second time:

| Reading | Where |
|---|---|
| the rotation cursor | :func:`syncr_domain.cursor.derive_cursor`, over the outcome log |
| outstanding debt, capped | :func:`syncr_domain.debt.outstanding_debt` |
| the keys the occurrences take | :func:`syncr_domain.identity.habit_occurrence_keys` |

**An occurrence carries no date.** Placement inside the week is free, so what a cadence produces
is a COUNT and the solver decides when. That is why the key is a position in the expansion
rather than a date, and why dragging an occurrence from Monday to Wednesday reads as the move
the user made rather than as a removal plus an addition.

**Debt occurrences come last, and the fresh ones keep the leading keys.** The keys are the
leading ``count`` of one sequence, so reducing a cadence drops the highest ordinals and re-keys
none of the survivors.

**Nothing here discharges debt.** The mark that an occurrence is a make-up is a fact about this
expansion and is not written onto an outcome, so a later week's derivation cannot tell a made-up
completion from a fresh one. A habit that has missed occurrences therefore keeps owing them until
a corrected confirmation says the miss did not happen, and a user who confirms three weeks late
materializes three weeks of debt at once, capped. Both are consequences of the log rather than
choices made here; ticket 1140 carries the question of whether completing a make-up should
discharge it, and it needs a column this product does not have yet.

**An interval cadence longer than a week is expanded every week.** ``~2d`` gives four
occurrences and ``~7d`` gives one, which is the rate the user declared. ``~30d`` also gives one,
which is twelve a year over-scheduled to fifty-two, because deciding that a monthly habit is not
due THIS week needs a reading of when it last occurred and no reader supplies one: the outcome
log is keyed by occurrence rather than by date, and the assembler holds no per-habit last
occurrence. Over-scheduling is visible to the user and under-scheduling is not, which is why the
rate rounds up rather than down. Ticket 1250 carries the decision.
"""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING, assert_never

from syncr_domain.cursor import derive_cursor
from syncr_domain.debt import outstanding_debt
from syncr_domain.habits import Daily, EveryApproxDays, TimesPerWeek
from syncr_domain.identity import BindingRef
from syncr_domain.weeks import Weekday
from syncr_solver.inputs import HabitOccurrence

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.habits.records import HabitRecord
    from syncr_api.plans.multipliers import DurationMultipliers
    from syncr_domain.habits import Cadence, Habit
    from syncr_domain.intervals import Instant
    from syncr_domain.outcomes import HabitOutcome

# How many dates a week holds. `Daily` produces one occurrence per date, and the figure is the
# weekday vocabulary's own length rather than a literal seven.
DAYS_PER_WEEK = len(Weekday)


def occurrences_in_a_week(cadence: Cadence) -> int:
    """How many occurrences of this cadence one week holds.

    A count per week is the count. ``Daily`` is one per date. An interval is the week divided by
    it, rounded UP, so a habit declared every two days appears four times and one declared every
    thirty appears once.
    """
    match cadence:
        case TimesPerWeek(count=count):
            return count
        case Daily():
            return DAYS_PER_WEEK
        case EveryApproxDays(days=days):
            return ceil(DAYS_PER_WEEK / days)
        case _:  # pragma: no cover - unreachable while Cadence has three members
            assert_never(cadence)


def habit_occurrences(
    habits: Sequence[HabitRecord],
    *,
    outcomes: Sequence[HabitOutcome],
    now: Instant,
    multipliers: DurationMultipliers,
) -> tuple[HabitOccurrence, ...]:
    """Every occurrence this week holds, fresh ones then made-up ones, per habit.

    ``now`` is the assembler's stamp and it clips the debt derivation to occurrences that have
    already come due: a session still ahead of the user has not been missed, so charging it
    would owe them work they have not yet had the chance to do.
    """
    expanded: list[HabitOccurrence] = []
    for record in habits:
        habit = record.as_habit()
        fresh = occurrences_in_a_week(habit.cadence)
        owed = outstanding_debt(habit, outcomes, now)
        variants = _variant_sequence(habit, outcomes, fresh + owed)
        duration = multipliers.scale_duration(habit.duration, area_id=record.area_id)
        for index in range(fresh + owed):
            expanded.append(
                HabitOccurrence(
                    binding=BindingRef.for_habit(record.id, index=index),
                    duration=duration,
                    variant=variants[index],
                    is_debt=index >= fresh,
                    area_id=record.area_id,
                    title=record.title,
                )
            )
    return tuple(expanded)


def _variant_sequence(
    habit: Habit, outcomes: Sequence[HabitOutcome], count: int
) -> Sequence[str | None]:
    """What each occurrence binds, in expansion order.

    A rotation advances across the week from wherever the log leaves it, so four occurrences of
    a four-variant rotation cover all four. A fixed habit repeats one content and a queue habit
    draws from the backlog when the solver binds it, so neither names a variant here.
    """
    if not habit.rotates:
        return [None] * count
    cursor = derive_cursor(habit, outcomes)
    return [habit.variants[(cursor + index) % len(habit.variants)] for index in range(count)]
