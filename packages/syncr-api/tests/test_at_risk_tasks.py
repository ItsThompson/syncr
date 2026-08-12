"""Which tasks a verdict puts at risk, over values rather than over a database.

The at-risk rule has one statement and this is where every case it has to get right is driven:
the three conditions a gap is matched on, the three shortfall kinds that are not read at all, and
the two absences that answer with nothing.

**The cases that would pass a looser rule.** A gap in another Area at the same instant, a gap at
another instant in the same Area, a task sharing both with the gap but absent from the names it
carries, and two tasks with one title in two Areas. Each of them is at risk under a rule that reads
one of the three conditions and not the other two, so the rule is exercised by the cases that
separate them rather than by the one case that satisfies everything.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.plans.at_risk import tasks_at_risk
from syncr_api.tasks.records import TaskRecord
from syncr_domain.feasibility import (
    Provenance,
    Shortfall,
    ShortfallKind,
    Verdict,
    minimum_chunk_shortfall,
)
from syncr_domain.tasks import NO_RECORDED_MINUTES, Priority, TaskStatus

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId

AN_HOUR = 60
THURSDAY_NINE = datetime(2026, 2, 12, 9, tzinfo=UTC)
FRIDAY_NINE = datetime(2026, 2, 13, 9, tzinfo=UTC)
COMPUTED_AT = datetime(2026, 2, 9, 8, tzinfo=UTC)

CAREER: AreaId = uuid4()
FITNESS: AreaId = uuid4()

TENANT = uuid4()


def a_task(*, title: str = "Leetcode", area_id: AreaId = CAREER, **changes: object) -> TaskRecord:
    """One open task with a deadline, which is the only shape a demand is computed for."""
    fields: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "area_id": area_id,
        "project_id": None,
        "title": title,
        "estimate_minutes": AN_HOUR,
        "deadline": THURSDAY_NINE,
        "priority": Priority.NORMAL,
        "min_chunk_minutes": 15,
        "splittable": True,
        "status": TaskStatus.OPEN,
        "recorded_minutes": NO_RECORDED_MINUTES,
        "completed_at": None,
        "created_at": COMPUTED_AT,
    }
    return TaskRecord(**{**fields, **changes})  # type: ignore[arg-type]


def a_deadline_gap(*names: str, area_id: AreaId = CAREER, **changes: object) -> Shortfall:
    """The gap the probe raises when work due before an instant does not fit before it."""
    fields: dict[str, object] = {
        "kind": ShortfallKind.DEADLINE_CAPACITY,
        "minutes": 80,
        "against": names or ("Leetcode",),
        "honoring": ("the 4h still uncommitted before it",),
        "deadline": THURSDAY_NINE,
        "area_id": area_id,
    }
    return Shortfall(**{**fields, **changes})  # type: ignore[arg-type]


def a_verdict(*shortfalls: Shortfall) -> Verdict:
    """A probe verdict carrying these gaps and claiming nothing it cannot."""
    return Verdict(
        feasible=False,
        provenance=Provenance.PROBE,
        computed_at=COMPUTED_AT,
        input_version=7,
        discretionary_minutes=6720,
        shortfalls=shortfalls,
    )


# --------------------------------------------------------------------------------
# The gap names the task: all three conditions hold
# --------------------------------------------------------------------------------


def test_a_task_a_deadline_gap_names_is_at_risk() -> None:
    task = a_task()

    assert tasks_at_risk(a_verdict(a_deadline_gap("Leetcode")), [task]) == {task.id}


def test_two_tasks_sharing_one_deadline_in_one_area_are_both_at_risk() -> None:
    """The demand is their sum, so the gap names both and neither is more at risk than the other."""
    first = a_task(title="Leetcode")
    second = a_task(title="F&F Past Papers")

    at_risk = tasks_at_risk(
        a_verdict(a_deadline_gap("F&F Past Papers", "Leetcode")), [first, second]
    )

    assert at_risk == {first.id, second.id}


def test_a_task_with_no_deadline_is_never_at_risk() -> None:
    """A gap is measured against an instant, and a task with none owes work by nothing."""
    undated = a_task(deadline=None)

    assert tasks_at_risk(a_verdict(a_deadline_gap("Leetcode")), [undated]) == frozenset()


# --------------------------------------------------------------------------------
# The three conditions, each falsified on its own
# --------------------------------------------------------------------------------


def test_a_gap_in_another_area_at_the_same_instant_does_not_name_this_task() -> None:
    """Both Areas owe work by Thursday, and the gap belongs to one of them."""
    career = a_task(area_id=CAREER)

    at_risk = tasks_at_risk(a_verdict(a_deadline_gap("Leetcode", area_id=FITNESS)), [career])

    assert at_risk == frozenset()


def test_a_gap_at_another_instant_in_the_same_area_does_not_name_this_task() -> None:
    """One Area with two deadlines is two demands, checked against two capacities."""
    due_thursday = a_task(deadline=THURSDAY_NINE)

    at_risk = tasks_at_risk(
        a_verdict(a_deadline_gap("Leetcode", deadline=FRIDAY_NINE)), [due_thursday]
    )

    assert at_risk == frozenset()


def test_a_task_sharing_the_pair_but_not_named_is_not_at_risk() -> None:
    """The case matching on the pair alone would sweep in.

    A task whose placements already cover its estimate before its own deadline produces no demand,
    so it is absent from the names the gap carries even though it shares the Area and the instant
    with the tasks that do.
    """
    named = a_task(title="Leetcode")
    covered = a_task(title="Mock interview prep")

    at_risk = tasks_at_risk(a_verdict(a_deadline_gap("Leetcode")), [named, covered])

    assert at_risk == {named.id}


def test_two_tasks_with_one_title_in_two_areas_separate_on_the_area() -> None:
    """The case matching on the title alone would sweep in."""
    career = a_task(title="Write up", area_id=CAREER)
    fitness = a_task(title="Write up", area_id=FITNESS)

    gap = a_deadline_gap("Write up", area_id=CAREER)

    at_risk = tasks_at_risk(a_verdict(gap), [career, fitness])

    assert at_risk == {career.id}


# --------------------------------------------------------------------------------
# The kinds that are not read
# --------------------------------------------------------------------------------


def test_a_packing_failure_naming_the_task_does_not_put_it_at_risk() -> None:
    """The fourth kind carries a title, an Area and a deadline, and the rule names the third kind.

    A packing failure says the capacity exists and could not be USED, which is a different statement
    from the work not fitting before the instant it is due.
    """
    task = a_task()
    packing = minimum_chunk_shortfall(
        minutes=50,
        chunk_minutes=50,
        against=("Leetcode",),
        deadline=THURSDAY_NINE,
        area_id=CAREER,
    )

    assert tasks_at_risk(a_verdict(packing), [task]) == frozenset()


@pytest.mark.parametrize(
    "kind", [ShortfallKind.FLOORS_EXCEED_CAPACITY, ShortfallKind.AREA_FLOOR_UNREACHABLE]
)
def test_a_floor_gap_puts_no_task_at_risk(kind: ShortfallKind) -> None:
    """Neither names a task at all: one is about the week and one is about an Area."""
    task = a_task()
    floor = replace(a_deadline_gap("Career"), kind=kind, against=("Career",))

    assert tasks_at_risk(a_verdict(floor), [task]) == frozenset()


# --------------------------------------------------------------------------------
# The two absences
# --------------------------------------------------------------------------------


def test_a_week_with_no_verdict_puts_nothing_at_risk() -> None:
    """A week with no plan has had nothing computed about it, so nothing about it is known."""
    assert tasks_at_risk(None, [a_task()]) == frozenset()


def test_a_verdict_that_found_no_gap_puts_nothing_at_risk() -> None:
    assert tasks_at_risk(a_verdict(), [a_task()]) == frozenset()
