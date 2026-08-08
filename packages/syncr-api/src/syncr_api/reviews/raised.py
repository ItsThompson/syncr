"""The raised items the weekly session opens with, and the sentence each one states.

Section 16's `SessionMode` lists the categories under one heading, and the notice-volume table gives
the panel they sit in one volume and one pigment: **panel, amber, in weekly-session mode only**. So
they are one collection with a kind on each member rather than one shape per category, and the
sentence a member renders is composed HERE rather than on a client: two clients would compose two
sentences from one row, and a figure the CLI printed differently from the screen is the defect the
pie review's own statements exist to prevent.

**The sentence carries every figure, and no field repeats one.** A count of weeks appears in the
words and nowhere else on the item, because a figure on the wire twice is a figure two surfaces can
render differently. What a client owns is the eyebrow a group of items sits under, which is a label
rather than a figure.

**Nothing here is an action, and that absence is the design.** There is deliberately no "carry
forward": an overdue task already surfaces as a raised item, so the backlog carries it implicitly
and the affordance would be a second way to say the same thing. A chronic skip offers nothing
either, because ``US-REV-02`` leaves reschedule, reduce scope, or drop to the user. A repeated
collision offers nothing because the fix could be a template change, an anchor-type change, or
nothing.

**Every kind derives its item from a reading someone else computed.** A floor at risk is the
verdict's own shortfall, an at-risk task is ``plans.at_risk``'s determination, a cadence item is the
plan of record's own blocks. Nothing recomputes a comparison another surface already makes: a second
arithmetic is how a task comes to be at risk in the session and fine on the Backlog screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from syncr_domain.feasibility import ShortfallKind, hours_and_minutes
from syncr_domain.identity import BindingKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from syncr_api.anchors.records import AnchorRecord
    from syncr_api.habits.records import HabitRecord
    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.debt import DebtReading
    from syncr_domain.feasibility import Verdict
    from syncr_domain.identifiers import HabitId
    from syncr_domain.plan import PlanDocument

    # What `BindingRef.content_key` answers: the binding with its week-scoped occurrence dropped.
    type ContentKey = tuple[BindingKind, UUID, int | None]


class RaisedKind(StrEnum):
    """What a raised item is about. One member per row of section 16's `raised` list."""

    CHRONIC_SKIP = "chronic_skip"
    HABIT_AT_DEBT_CAP = "habit_at_debt_cap"
    REPEATED_COLLISION = "repeated_collision"
    OVERDUE_TASK = "overdue_task"
    AT_RISK_TASK = "at_risk_task"
    FLOOR_AT_RISK = "floor_at_risk"
    NEW_ANCHOR = "new_anchor"
    CADENCE_DUE = "cadence_due"


# The two floor gaps a verdict can report. `deadline_capacity` and `minimum_chunk_unplaceable` are
# deliberately absent: the first is what makes a TASK at risk, which is its own kind, and the second
# is a packing failure rather than a floor.
FLOOR_SHORTFALLS = (ShortfallKind.FLOORS_EXCEED_CAPACITY, ShortfallKind.AREA_FLOOR_UNREACHABLE)


@dataclass(frozen=True, slots=True, kw_only=True)
class RaisedItem:
    """One thing the session raises: what it is about, what it names, and what it says.

    ``key`` is stable for one thing across two reads of one session, so a client keys a list on it
    rather than on a position. It is not an identifier of anything: an item is a reading rather than
    a row, and nothing addresses one.

    There is no count field. Every figure an item states is in ``statement``, which is the one place
    it is spelled: a count on the wire as well as in the words would be one fact twice, and the
    surface that rendered both would have to choose which to trust.
    """

    key: str
    kind: RaisedKind
    title: str
    statement: str


def habit_debt_items(
    habits: Sequence[HabitRecord], readings: Mapping[HabitId, DebtReading]
) -> list[RaisedItem]:
    """One item per habit its own policy raises, through the surface chronic skips use.

    ``US-HAB-07`` asks for exactly that: reaching the cap raises the habit "through the same surface
    chronic skips use", so this is a kind of raised item rather than a second mechanism. The reading
    decides whether a habit is raised at all, because the policy table lives in
    ``syncr_domain.debt`` and a condition restated here would be a second copy of it.
    """
    return [
        RaisedItem(
            key=f"{RaisedKind.HABIT_AT_DEBT_CAP}:{habit.id}",
            kind=RaisedKind.HABIT_AT_DEBT_CAP,
            title=habit.title,
            statement=reading.statement,
        )
        for habit in habits
        if (reading := readings.get(habit.id)) is not None and reading.raised_in_weekly_session
    ]


def overdue_items(tasks: Iterable[TaskRecord], *, now: datetime) -> list[RaisedItem]:
    """One item per open task whose deadline has passed.

    There is no "carry forward" action beside it, deliberately: the task is still in the backlog,
    so the next solve may place it, and an affordance saying so would be a control that changes
    nothing.
    """
    return [
        RaisedItem(
            key=f"{RaisedKind.OVERDUE_TASK}:{task.id}",
            kind=RaisedKind.OVERDUE_TASK,
            title=task.title,
            statement=(
                f"Overdue: it was due {task.deadline:%-d %b} and "
                f"{hours_and_minutes(task.remaining_minutes())} of it is left."
            ),
        )
        for task in tasks
        if task.deadline is not None and task.deadline < now
    ]


def at_risk_items(tasks: Iterable[TaskRecord]) -> list[RaisedItem]:
    """One item per task the week's verdict puts at risk.

    Which tasks those are is ``plans.at_risk``'s answer over the same verdict the panel renders, so
    the session and the Backlog screen cannot disagree about a row.
    """
    return [
        RaisedItem(
            key=f"{RaisedKind.AT_RISK_TASK}:{task.id}",
            kind=RaisedKind.AT_RISK_TASK,
            title=task.title,
            statement=(
                "At risk: the week cannot fit the work this task needs before its deadline. The "
                "verdict below names the gap."
            ),
        )
        for task in tasks
    ]


def floor_items(verdict: Verdict | None) -> list[RaisedItem]:
    """One item per floor the week's verdict cannot reach.

    Read off the verdict rather than compared here, so the panel's figure and this row's figure are
    one arithmetic. A week with no verdict raises none: nothing has been computed about it.
    """
    if verdict is None:
        return []
    return [
        RaisedItem(
            key=f"{RaisedKind.FLOOR_AT_RISK}:{shortfall.kind}:{shortfall.area_id}",
            kind=RaisedKind.FLOOR_AT_RISK,
            title=", ".join(shortfall.against),
            statement=(
                f"{hours_and_minutes(shortfall.minutes)} short of the floor this week reserves. "
                "The verdict below offers what could be conceded."
            ),
        )
        for shortfall in verdict.shortfalls
        if shortfall.kind in FLOOR_SHORTFALLS
    ]


def new_anchor_items(arriving: Iterable[AnchorRecord]) -> list[RaisedItem]:
    """One item per commitment landing in the week being planned that last week did not hold."""
    return [
        RaisedItem(
            key=f"{RaisedKind.NEW_ANCHOR}:{anchor.id}",
            kind=RaisedKind.NEW_ANCHOR,
            title=anchor.title,
            statement=(
                f"New commitment, {anchor.interval.start:%a %-d %b %H:%M} for "
                f"{hours_and_minutes(anchor.interval.total_minutes())}. It is immovable, so the "
                "week is planned around it."
            ),
        )
        for anchor in arriving
    ]


def cadence_items(document: PlanDocument | None, habits: Sequence[HabitRecord]) -> list[RaisedItem]:
    """One item per habit the week being planned holds occurrences for, with the count.

    Taken from the plan of record's own blocks rather than from a fresh cadence expansion, and the
    difference matters: the expansion says what the cadence asks for and the document says what the
    week actually holds, which is the figure the session is reviewing. A week with no plan holds
    nothing, and the payload's own statement says why.
    """
    if document is None:
        return []
    by_habit = {habit.id: habit for habit in habits}
    counted: dict[HabitId, int] = {}
    for block in document.blocks:
        if block.binding.kind is BindingKind.HABIT and block.binding.entity_id in by_habit:
            counted[block.binding.entity_id] = counted.get(block.binding.entity_id, 0) + 1
    return [
        RaisedItem(
            key=f"{RaisedKind.CADENCE_DUE}:{habit_id}",
            kind=RaisedKind.CADENCE_DUE,
            title=by_habit[habit_id].title,
            statement=f"{count} occurrence{'' if count == 1 else 's'} due in this week's plan.",
        )
        for habit_id, count in counted.items()
    ]
