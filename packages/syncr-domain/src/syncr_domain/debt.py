"""Debt accumulation, the cap, and what a miss raises in the weekly session.

```
occurrence due
      │
      ├── confirmed complete ─────────────▶ rotation cursor advances, and a made-up
      │                                     occurrence's completion discharges one
      │                                     unit of debt
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

**A completed make-up discharges the debt it was placed for.** An outcome carries whether the
occurrence it records was a make-up, and a confirmed completion of a marked occurrence settles a
charge the log holds when that completion comes due. So what the log holds against a habit falls
when the user does the work, and "missed occurrences not yet made up" is the literal reading of it
rather than an approximation of it. A credit reaches no further than the charge standing when it
arrives, so it cannot outlive the miss it settled.

**A completion of a FRESH occurrence discharges nothing.** A four-a-week habit that owes four
and then has a clean week has done the four it was due, not the four it owes, so crediting any
completion would report a backlog of nothing while four occurrences are still outstanding.

**Two further things the log settles on its own, and neither is a discharge.** A corrected
confirmation says the occurrence was not missed after all, and the charge disappears because
the derivation reads the log from scratch. A made-up occurrence the user skips again is a miss
of its own and charges as one. The walk holds no state between readings, which is what keeps a
stored cursor by another name out of the module. The one figure stored anywhere is the walked
count itself, maintained by the outcome write through :func:`charged_misses` and read back
through :func:`stored_reading`: it is a cache of this module's own arithmetic over the same
rows, so a reader that cannot afford the log's whole history does not answer with a narrower
walk instead.

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
    ``misses`` is what the log still charges the habit: confirmed skips, less the made-up
    occurrences completed against them, so it falls as the backlog is worked off.
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

    An occurrence is made up when the log holds a confirmed completion of the made-up occurrence
    placed for it. Zero for ``forgive``, whose misses vanish, and zero for ``escalate``, which
    raises the habit rather than rescheduling anything. Only ``debt`` accumulates.
    """
    return debt_reading(habit, outcomes, as_of).outstanding


def debt_reading(habit: Habit, outcomes: Sequence[HabitOutcome], as_of: Instant) -> DebtReading:
    """Every figure a habit's misses produce, over one log and one policy."""
    return stored_reading(habit, charged_misses(habit, outcomes, as_of))


def stored_reading(habit: Habit, misses: int) -> DebtReading:
    """Every figure a habit's misses produce, from a count taken beside the log.

    The same policy table :func:`debt_reading` walks, stated over the count rather than over the
    rows. It is what a stored charge reads through: the outcome write maintains the walked count on
    the habit row, so a reader that cannot afford the log's whole history still answers with the
    figures this module defines, and the count is exact wherever the log is because it is the same
    walk, run where the rows were written.
    """
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


def charged_misses(habit: Habit, outcomes: Sequence[HabitOutcome], as_of: Instant) -> int:
    """What this habit's log still charges by ``as_of``: confirmed skips, less the make-ups done.

    Walked oldest-due first rather than counted, because a completed make-up settles a charge the
    log holds **when it arrives**. Differencing two totals would let a make-up whose own charge has
    since been corrected away carry its credit forward and settle an unrelated miss years later,
    which is a charge nothing in the log has made good.

    The clip is what ``as_of`` is for. A week's plan can already hold outcome rows for occurrences
    later in the week, and an occurrence that has not come due yet has not been missed, so counting
    it would charge the user for a session still ahead of them. It clips both kinds of row, because
    a make-up still ahead of the user has not been done either.

    The floor is per credit and it is reachable rather than defensive: correcting the miss that
    placed a make-up leaves a log holding the completion and not the skip. A negative figure would
    reach the week's expansion as a count added to the cadence, where it would silently drop fresh
    occurrences from the week rather than fail.
    """
    charged = 0
    for outcome in _due_oldest_first(habit, outcomes, as_of):
        if outcome.is_confirmed_miss:
            charged += 1
        elif outcome.is_confirmed_make_up_completion:
            charged = max(charged - 1, 0)
    return charged


def _due_oldest_first(
    habit: Habit, outcomes: Sequence[HabitOutcome], as_of: Instant
) -> list[HabitOutcome]:
    """This habit's outcomes that had come due by ``as_of``, in the order they came due.

    The order is imposed here rather than taken from the sequence, because the log's readers state
    no order: a reader keyed by entity returns rows in whatever order its index holds them, and two
    readers of one log may differ. Sorting on the instant each occurrence came due is the same
    absolute-instant comparison the clip makes, so no zone and no date arithmetic enter with it.

    It is the instant the occurrence came DUE and not the instant the day was confirmed. A day
    confirmed weeks late is a miss of the day it was due, so the make-up placed for it arrives after
    that charge; ordering by the confirmation would put the credit first and spend it on nothing.

    Two occurrences of one habit can come due at the same instant. The tie reads the charge as
    standing when the credit arrives, which is the direction that never leaves work the user did
    unspent.
    """
    due = [
        outcome
        for outcome in outcomes
        if outcome.habit_id == habit.id and outcome.occurred_at <= as_of
    ]
    return sorted(due, key=lambda row: (row.occurred_at, row.is_confirmed_make_up_completion))


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
