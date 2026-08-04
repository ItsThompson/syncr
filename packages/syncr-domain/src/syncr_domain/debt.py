"""Debt accumulation, the cap, and what a miss raises in the weekly session.

```
occurrence due
      │
      ├── confirmed complete ─────────────▶ rotation cursor advances
      │
      └── confirmed skipped ──────────────▶ miss_policy decides
                                              │
              ┌───────────────────────────────┼───────────────────────────┐
              ▼                               ▼                           ▼
          forgive                          debt                       escalate
   the occurrence vanishes.       reschedules and accumulates.   raised in the next
   No downstream effect.          Capped at debt_cap_periods.    weekly session.
                                              │
                                  ┌───────────┴────────────┐
                                  ▼                        ▼
                          below the cap              AT the cap
                          debt += 1                  miss is FORGIVEN, and the
                                                     habit is raised in the
                                                     weekly session
```

**Only a CONFIRMED skip is a miss, and an unconfirmed day is neither a miss nor a completion.**
That is a narrowing, and it is stated here because it is a product behavior rather than a detail: a
user who stops confirming days accrues no debt and raises no ``escalate`` habit, so the two
policies that exist to chase the user go quiet for exactly the user who disengaged. The reasons are
that an unconfirmed day is excluded from reviews and from learning everywhere else, and that the
default state of an unconfirmed block is ``presumed``, so charging an unconfirmed row would charge
every day the user actually did along with the ones they did not. Confirming the day later settles
it in whichever direction the user chooses, which is what makes the narrowing safe rather than
lossy.

**The cap is a ceiling, not a decay curve.** Unbounded accumulation would make the backlog
useless, and hitting the cap reuses the chronic-skip surface the weekly session already has
rather than inventing a half-life the user would have to reason about.

**Nothing here discharges debt, and that is a property of the log rather than a choice.** The
week assembler marks a made-up occurrence ``is_debt`` when it places one, but that mark is not
written onto the outcome, so no later re-derivation can tell a made-up occurrence from a fresh
one. A discharge rule would therefore have to hold state of its own, which is a stored cursor
by another name: exactly the shape the derived rotation cursor exists to avoid. What the log
*can* say is that an occurrence was not missed after all, and that is what a corrected
confirmation says: the charge disappears because the derivation reads the log from scratch.

**No date arithmetic happens here.** ``as_of`` clips the log to occurrences that have already
come due, which is an absolute-instant comparison and needs no zone, so a daylight-saving
transition, a year boundary, and a tenant who changes zone are all invisible to it. Cadence
periods are counted, never measured: ``occurrences_per_period`` answers from the cadence
alone.

**Both figures a reading carries are stated over the same outcomes**, so a caller cannot read
one against a wider log than the other. Which log that is, is the caller's: the week assembler
passes the whole log because debt accumulates over all of it, and the weekly session passes
the week under review because an ``escalate`` raise is about the week that just happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from syncr_domain.habits import MissPolicy, occurrences_per_period

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.habits import Habit
    from syncr_domain.intervals import Instant
    from syncr_domain.outcomes import HabitOutcome


@dataclass(frozen=True, slots=True)
class DebtReading:
    """What the misses in one outcome log amount to under a habit's miss policy.

    ``outstanding`` is what the week assembler adds to a week as made-up occurrences.
    ``raised_in_weekly_session`` is the field chronic skips already use, and it is how both
    the debt cap and the ``escalate`` policy reach the weekly session's raised items.
    """

    misses: int
    outstanding: int
    cap: int
    forgiven_at_cap: int
    raised_in_weekly_session: bool
    statement: str


def debt_cap(habit: Habit) -> int:
    """The ceiling on outstanding debt: cadence periods times occurrences per period.

    A ``4 / wk`` habit capped at two periods owes at most eight sessions. A ``Daily`` habit
    capped at two periods owes at most two days, and an ``~7d`` habit at most two intervals.
    Each reads as "this many cadence periods behind", which is the figure the user set.
    """
    return habit.debt_cap_periods * occurrences_per_period(habit.cadence)


def outstanding_debt(habit: Habit, outcomes: Sequence[HabitOutcome], as_of: Instant) -> int:
    """Missed debt-policy occurrences not yet made up, clamped to :func:`debt_cap`.

    Zero for ``forgive``, whose misses vanish, and zero for ``escalate``, which raises the
    habit rather than rescheduling anything. Only ``debt`` accumulates.
    """
    return debt_reading(habit, outcomes, as_of).outstanding


def debt_reading(habit: Habit, outcomes: Sequence[HabitOutcome], as_of: Instant) -> DebtReading:
    """Every figure a habit's misses produce, over one log and one policy."""
    misses = _misses(habit, outcomes, as_of)
    cap = debt_cap(habit)
    match habit.miss_policy:
        case MissPolicy.FORGIVE:
            return _reading(misses, cap, outstanding=0, forgiven=0, raised=False)
        case MissPolicy.DEBT:
            return _reading(
                misses,
                cap,
                outstanding=min(misses, cap),
                forgiven=max(0, misses - cap),
                raised=misses > cap,
            )
        case MissPolicy.ESCALATE:
            return _reading(misses, cap, outstanding=0, forgiven=0, raised=misses > 0)
        case _:  # pragma: no cover - unreachable while MissPolicy has three members
            assert_never(habit.miss_policy)


def _misses(habit: Habit, outcomes: Sequence[HabitOutcome], as_of: Instant) -> int:
    """Confirmed skips of this habit's occurrences that had come due by ``as_of``.

    The clip is what ``as_of`` is for. A week's plan can already hold outcome rows for
    occurrences later in the week, and an occurrence that has not come due yet has not been
    missed, so counting it would charge the user for a session still ahead of them.
    """
    return sum(
        1
        for outcome in outcomes
        if outcome.habit_id == habit.id
        and outcome.is_confirmed_miss
        and outcome.occurred_at <= as_of
    )


def _reading(
    misses: int, cap: int, *, outstanding: int, forgiven: int, raised: bool
) -> DebtReading:
    return DebtReading(
        misses=misses,
        outstanding=outstanding,
        cap=cap,
        forgiven_at_cap=forgiven,
        raised_in_weekly_session=raised,
        statement=_statement(
            misses, cap, outstanding=outstanding, forgiven=forgiven, raised=raised
        ),
    )


def _statement(misses: int, cap: int, *, outstanding: int, forgiven: int, raised: bool) -> str:
    if forgiven:
        return (
            f"{outstanding} of {cap} owed, which is the cap. {forgiven} further "
            f"{_occurrences(forgiven)} were forgiven rather than added, and the habit is "
            "raised in the weekly session."
        )
    if raised:
        return f"{misses} missed {_occurrences(misses)}, raised in the next weekly session."
    if outstanding:
        return f"{outstanding} of {cap} owed."
    if misses:
        return f"{misses} missed {_occurrences(misses)}, and this habit's policy owes nothing."
    return "Nothing owed."


def _occurrences(count: int) -> str:
    return "occurrence" if count == 1 else "occurrences"
