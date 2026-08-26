"""Expanding a habit's cadence into the occurrences one week holds.

A habit answers *when and how often*; this answers *how many, this week, and what each one
holds*. Three readings of stored state meet here, and each is already implemented in the pure
package rather than a second time:

| Reading | Where |
|---|---|
| the rotation cursor | :func:`syncr_domain.cursor.derive_cursor`, over the outcome log |
| outstanding debt, capped | :func:`syncr_domain.debt.stored_reading`, over the stored charge |
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
choices made here.

**An interval longer than the week expands once, in the week it comes due.** ``~2d`` gives four
occurrences and ``~7d`` gives one every week, because an interval no longer than the week it
expands into repeats at its declared rate inside that week: the rate is observable in it.
``~30d`` holds less than one occurrence a week, so no rate can place it, and the rule is a date:
the habit expands in the week whose span holds its last recorded occurrence plus the interval,
and not in the one after. A habit with no recorded occurrence at all is due immediately. A due
week the user misses is not re-expanded later; what a miss owes is the miss policy's answer, and
the cadence states only when the next occurrence comes due. The log read that supplies the last
occurrence reaches back exactly one declared interval past the week, which is the bound the
binding expression index serves: anything older is further from due than the rule can reach, and
only the question "has this habit ever been recorded" needs to reach past it.
"""

from __future__ import annotations

from datetime import timedelta
from math import ceil
from typing import TYPE_CHECKING, assert_never

from syncr_domain.cursor import derive_cursor
from syncr_domain.habits import Daily, EveryApproxDays, TimesPerWeek
from syncr_domain.identity import BindingRef
from syncr_domain.weeks import Weekday
from syncr_solver.inputs import HabitOccurrence

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.habits.records import HabitRecord
    from syncr_api.plans.multipliers import DurationMultipliers
    from syncr_domain.habits import Cadence, Habit
    from syncr_domain.identifiers import HabitId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.outcomes import HabitOutcome

# How many dates a week holds. `Daily` produces one occurrence per date, and the figure is the
# weekday vocabulary's own length rather than a literal seven.
DAYS_PER_WEEK = len(Weekday)


def occurrences_in_a_week(cadence: Cadence) -> int:
    """How many occurrences of this cadence one week holds at its declared rate.

    A count per week is the count. ``Daily`` is one per date. An interval is the week divided by
    it, rounded UP, so a habit declared every two days appears four times and one declared every
    thirty appears once. For an interval longer than the week this rate is only the ceiling a due
    week reaches; :func:`expansions_in_a_week` decides whether any week reaches it.
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


def expansions_in_a_week(
    cadence: Cadence,
    *,
    last_recorded: Instant | None,
    has_recorded: bool,
    span: Interval,
) -> int:
    """How many fresh occurrences THIS week holds: the rate, gated by the due rule.

    An interval no longer than the week repeats at its declared rate inside that week, so the
    rate answers alone and no reading of the log is needed. A longer one holds less than one
    occurrence a week, so it expands exactly once when the week's span holds ``last recorded +
    interval`` and in no other week.

    ``last_recorded`` comes from the bounded read, so ``None`` leaves two cases apart, and
    ``has_recorded`` -- whether the whole log names the habit at all -- is what tells them:
    nothing ever recorded means the habit is due immediately, while a habit whose last occurrence
    lies before the window is strictly overdue, past every week that occurrence could make due.
    """
    match cadence:
        case EveryApproxDays(days=days) if days > DAYS_PER_WEEK:
            if last_recorded is None:
                return 0 if has_recorded else 1
            due_at = last_recorded + timedelta(days=days)
            return 1 if span.start <= due_at < span.end else 0
        case _:
            return occurrences_in_a_week(cadence)


def log_window(habits: Sequence[HabitRecord], *, span: Interval) -> Instant:
    """How far back the last-occurrence read needs to reach: the week minus one interval.

    The longest interval any of the tenant's habits declares, plus one day of slack past the
    week's start, is strictly further back than any occurrence that could make this week due.
    Reading the log bounded to it keeps the scan inside the range the binding expression index
    serves instead of walking the tenant's whole history for dates the rule never reads.
    """
    declared = (record.as_habit().cadence for record in habits)
    longest = max(
        (cadence.days for cadence in declared if isinstance(cadence, EveryApproxDays)),
        default=0,
    )
    return span.start - timedelta(days=longest + 1)


def habit_occurrences(
    habits: Sequence[HabitRecord],
    *,
    outcomes: Sequence[HabitOutcome],
    owed: Mapping[HabitId, int],
    last_recorded: Mapping[HabitId, Instant | None],
    span: Interval,
    multipliers: DurationMultipliers,
) -> tuple[HabitOccurrence, ...]:
    """Every occurrence this week holds, fresh ones then made-up ones, per habit.

    ``outcomes`` is the whole log and feeds the rotation cursor, which accumulates over history and
    survives no narrower read. ``owed`` is each habit's outstanding debt as its stored charge
    answers it, capped by policy before it arrives: the walk that produces the charge runs beside
    the rows on the outcome write, so this expansion never re-walks the tenant's history to place
    make-ups. ``last_recorded`` is the bounded per-habit reading the due rule needs, keyed by habit
    id with ``None`` where the window holds no row.
    """
    expanded: list[HabitOccurrence] = []
    recorded_ever = {outcome.habit_id for outcome in outcomes}
    for record in habits:
        habit = record.as_habit()
        fresh = expansions_in_a_week(
            habit.cadence,
            last_recorded=last_recorded.get(record.id),
            has_recorded=record.id in recorded_ever,
            span=span,
        )
        owed_count = owed.get(record.id, 0)
        variants = _variant_sequence(habit, outcomes, fresh + owed_count)
        duration = multipliers.scale_duration(habit.duration, area_id=record.area_id)
        for index in range(fresh + owed_count):
            expanded.append(
                HabitOccurrence(
                    binding=BindingRef.for_habit(record.id, index=index),
                    duration=duration,
                    binding_source=habit.binding_source,
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
