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
repository reads, which `19` budgets separately at 100 ms, and it excludes serialization and the
conditional write. Those are the right exclusions for a budget stated over ``solve``, and they are
the reason this number must not be read as an end-to-end request budget.
"""

from __future__ import annotations

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

if TYPE_CHECKING:
    from syncr_solver.inputs import SolveInputs

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
    tasks = tuple(
        EligibleTask(
            binding=BindingRef.for_task(UUID(f"ffffffff-0000-4000-8000-{index:012d}")),
            remaining_minutes=60,
            priority=Priority.NORMAL,
            min_chunk_minutes=15,
            splittable=True,
            area_id=_AREAS[index % len(_AREAS)],
            title=f"Task {index}",
            deadline=at(9, day=4 + index % 3),
        )
        for index in range(TASKS)
    )
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


def main() -> None:
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


if __name__ == "__main__":
    main()
