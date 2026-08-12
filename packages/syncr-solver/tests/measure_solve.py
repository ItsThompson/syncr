"""Measure a solve at the size this product is sized against, and print the table.

``python -m tests.measure_solve`` from the member's directory. Not a test: a wall-time assertion
measures the machine it runs on, which is why the suite asserts the iteration count instead. This is
the reproducible measurement the two numbers in :mod:`syncr_solver.budget` were chosen against, so
the next person to change either can re-measure what it was sized against rather than rebuild the
week from a paragraph.

The week is the reference week with its content scaled up: nine concrete entries a date, eleven
habits at five occurrences each, twenty-four tasks with fifteen-minute minimum chunks, Area targets
widened and the daily cap dropped. That is the target state rather than the status quo, which is
roughly 62 blocks a week: the product's job is to fill the discretionary hours that currently sit in
no block at all.

The figure is wall time around ``solve`` and nothing else. It excludes the week assembler's eleven
repository reads, which are budgeted separately at 100 ms, and it excludes serialization and the
conditional write. Those are the right exclusions for a budget stated over ``solve``, and they are
the reason this number must not be read as an end-to-end request budget.

## Two modes

``table`` is the default and is the one above. ``yield`` reports what each of the four move kinds
bought on the saturated week and on the reference week: the moves it offered, the moves the
objective accepted, the iteration the last acceptance landed on, and the wall time the kind spent.
Nothing in the package publishes those, because ``Improved`` carries the totals rather than the
per-kind split, and the choice between bounding the search's tail and re-ordering its kinds cannot
be made without them. :mod:`tests.search_yield` is the instrument, and its own faithfulness to the
shipped loop is asserted in ``tests/test_search_yield.py`` rather than assumed here.
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_domain.habits import BindingSource, Duration
from syncr_domain.identity import BindingRef, date_occurrence_key
from syncr_domain.tasks import Priority
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_solver import solve
from syncr_solver.budget import SolveBudget
from syncr_solver.inputs import (
    EligibleTask,
    EntryBinding,
    HabitOccurrence,
    MaterializedEntry,
)
from tests.objective_weeks import hand_tuned_weights
from tests.reference_week import CAREER, FITNESS, STUDY, at, between, on, reference_week
from tests.search_yield import constructed, descend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_solver.inputs import SolveInputs
    from tests.search_yield import Yield

# Nine more entries a date, spread across the day so they compete with the content rather than
# stacking into one hour. Every one is fifteen or thirty minutes, which is what a dense real day
# holds most of.
_DENSE_ENTRIES: Final = (
    ("Breakfast", 7.0, 7.5, FITNESS),
    ("Tidy", 8.0, 8.25, FITNESS),
    ("Standup", 9.0, 9.25, CAREER),
    ("Lunch", 12.5, 13.0, FITNESS),
    ("Walk the dog", 16.0, 16.5, FITNESS),
    ("Inbox", 17.0, 17.25, CAREER),
    ("Review", 18.0, 18.25, CAREER),
    ("Journal", 21.5, 21.75, STUDY),
    ("Plan tomorrow", 22.0, 22.25, STUDY),
)

_AREAS: Final = (FITNESS, CAREER, STUDY)

HABITS: Final = 11
OCCURRENCES_EACH: Final = 5
TASKS: Final = 24

# What closes the last 330 minutes the scaled week still leaves unallocated. Eight hours of further
# task work rather than a widened Area target, because the target is what the objective is judged
# against and the demand is what the packer has to place. Measured: 4 more tasks leave 15 minutes
# and 8 leave none, at 229 blocks.
SATURATING_TASKS: Final = 8


def _tasks(count: int, *, identity: str, title: str, first: int = 0) -> tuple[EligibleTask, ...]:
    """An hour of splittable work each, spread across the three Areas, due late in the week."""
    return tuple(
        EligibleTask(
            binding=BindingRef.for_task(UUID(f"{identity}-0000-4000-8000-{index:012d}")),
            remaining_minutes=60,
            priority=Priority.NORMAL,
            min_chunk_minutes=15,
            splittable=True,
            area_id=_AREAS[index % len(_AREAS)],
            title=f"{title} {index}",
            deadline=at(9, day=4 + index % 3),
        )
        for index in range(first, first + count)
    )


def a_dense_week() -> SolveInputs:
    """The reference week with its content scaled to the size the budget is stated over."""
    week = reference_week()
    entries = tuple(
        MaterializedEntry(
            entry_id=UUID(f"dddddddd-0000-4000-8000-{index:012d}"),
            occurrence_key=date_occurrence_key(on(day)),
            kind=TemplateEntryKind.CONCRETE,
            interval=between(start, end, day=day),
            flex_band_minutes=0,
            area_id=area,
            title=title,
            binding=EntryBinding(
                target=BindingTarget.HABIT,
                entity_id=UUID(f"dddddddd-0000-4000-8000-{index:012d}"),
            ),
        )
        for index, (title, start, end, area) in enumerate(_DENSE_ENTRIES)
        for day in range(7)
    )
    occurrences = tuple(
        HabitOccurrence(
            binding=BindingRef.for_habit(
                UUID(f"eeeeeeee-0000-4000-8000-{habit:012d}"), index=index
            ),
            duration=Duration.fixed(15),
            area_id=_AREAS[habit % len(_AREAS)],
            title=f"Habit {habit}",
            binding_source=BindingSource.FIXED,
        )
        for habit in range(HABITS)
        for index in range(OCCURRENCES_EACH)
    )
    tasks = _tasks(TASKS, identity="ffffffff", title="Task")
    return replace(
        week,
        template_entries=(*week.template_entries, *entries),
        habit_occurrences=(*week.habit_occurrences, *occurrences),
        eligible_tasks=(*week.eligible_tasks, *tasks),
        areas=tuple(
            replace(area, target_minutes=area.target_minutes * 3, max_per_day_minutes=None)
            for area in week.areas
        ),
    )


def a_saturated_week() -> SolveInputs:
    """The dense week with nothing left unallocated, which is where a relocation has nowhere to go.

    ``a_dense_week`` leaves 330 minutes in no block, so the search can still relocate. A week with
    none is a different regime and it is the one a stop condition would be sized against, so it is
    built here from the week the budget's own numbers were measured on: the same content plus eight
    more hours of task work, which is what closes the last gap.
    """
    week = a_dense_week()
    return replace(
        week,
        eligible_tasks=(
            *week.eligible_tasks,
            *_tasks(SATURATING_TASKS, identity="aaaaaaaa", title="Saturating"),
        ),
    )


def timed(
    week: SolveInputs, budget: SolveBudget, *, runs: int = 5
) -> tuple[float, float, int, int]:
    """The median and the worst of ``runs`` solves, with the blocks and the iterations they held."""
    weights = hand_tuned_weights()
    elapsed = []
    for _ in range(runs):
        started = time.perf_counter()
        found = solve(week, weights, budget=budget)
        elapsed.append(time.perf_counter() - started)
    return (
        statistics.median(elapsed),
        max(elapsed),
        len(found.document.blocks),
        found.iterations,
    )


def report_yield() -> None:
    """What each move kind offered, cost and bought, on each of the three weeks.

    Three because the choice the figures inform is a trade between two of them and the third is the
    regime the other two are not. The reference week is the loose one a stop must not cost. The
    dense week is the one the budget's own numbers were sized against, and it still leaves 330
    minutes in no block. The saturated week is the dense week with none.

    The solve's own wall time is measured beside the descent's, so the search's share of it is a
    figure rather than an impression.
    """
    weights = hand_tuned_weights()
    budget = SolveBudget()
    for label, week in (
        ("saturated", a_saturated_week()),
        ("dense", a_dense_week()),
        ("reference", reference_week()),
    ):
        attempt = constructed(week, weights, budget=budget)
        found = descend(attempt, weights, budget=budget)
        median, _, _, iterations = timed(week, budget, runs=3)
        solved = solve(week, weights, budget=budget)
        print(f"=== {label} week")
        print(
            f"blocks         {len(attempt.document().blocks):8d}      "
            f"the plan the descent starts from; {len(solved.document.blocks)} once it ends"
        )
        print(f"unallocated    {solved.document.unallocated_minutes:8d} m")
        print(f"solve p50      {median * 1000:8.1f} ms   over three runs")
        print(
            f"descent        {found.seconds * 1000:8.1f} ms   {found.seconds / median:5.1%} of it"
        )
        print(f"iterations     {found.iterations:8d}      solve reports {iterations}")
        print(f"accepted       {found.accepted:8d}")
        print(f"last accepted  {_at(found.last_acceptance):>8}      tail {found.tail} iterations")
        print(f"longest run before an acceptance: {found.longest_run_before_an_acceptance}")
        print(f"objective total{found.total:8.4f}")
        print(f"    {'kind':10} {'considered':>10} {'accepted':>8} {'ms':>9} {'share':>7}")
        for column in found.kinds:
            share = column.seconds / found.seconds if found.seconds else 0.0
            print(
                f"    {column.kind:10} {column.considered:10d} {column.accepted:8d} "
                f"{column.seconds * 1000:9.1f} {share:7.1%}"
            )
        print(f"    {'drained':10} {'':10} {'':8} {found.drained_seconds * 1000:9.3f}")
        print(f"acceptances    {_acceptances(found)}")
        print()


def _at(iteration: int | None) -> str:
    """The iteration an acceptance landed on, or the word for a descent that accepted nothing."""
    return "none" if iteration is None else str(iteration)


def _acceptances(found: Yield) -> str:
    """Every acceptance as the iteration it landed on and the kind that produced it."""
    return (
        ", ".join(f"{taken.iteration}:{taken.kind}" for taken in found.acceptances)
        if found.acceptances
        else "none"
    )


def report_table() -> None:
    week = a_dense_week()
    first = solve(week, hand_tuned_weights())
    print(f"blocks       {len(first.document.blocks)}")
    print(f"composition  {dict(Counter(b.origin.value for b in first.document.blocks))}")
    print(f"slots        {len(first.document.empty_slots)}")
    print(f"blocked      {len(first.blocked_log)}")
    print(f"unallocated  {first.document.unallocated_minutes}m")
    for term, cost in first.objective_breakdown.costs().items():
        print(f"    {term:20} {cost:10.4f}  {first.objective_breakdown.share_of(term) * 100:5.1f}%")
    print(f"    {'TOTAL':20} {first.objective_breakdown.total():10.4f}")
    print()
    for label, budget in (
        ("construction only", SolveBudget(move_evaluations=0)),
        ("search 100", SolveBudget(move_evaluations=100)),
        ("shipped", SolveBudget()),
    ):
        median, worst, blocks, iterations = timed(week, budget)
        print(
            f"{label:20} p50 {median * 1000:7.1f} ms  max {worst * 1000:7.1f} ms  "
            f"blocks {blocks:4d}  iterations {iterations:4d}"
        )
    counted = {solve(week, hand_tuned_weights()).iterations for _ in range(3)}
    print(f"\niterations across three runs: {counted}")


def main(argv: Sequence[str] | None = None) -> None:
    """Run one mode. ``table`` is the default, so the invocation the budget cites is unchanged."""
    parser = argparse.ArgumentParser(description="Measure a solve at the size it is sized against.")
    parser.add_argument("mode", nargs="?", default="table", choices=("table", "yield"))
    if parser.parse_args(argv).mode == "yield":
        report_yield()
    else:
        report_table()


if __name__ == "__main__":
    main()
