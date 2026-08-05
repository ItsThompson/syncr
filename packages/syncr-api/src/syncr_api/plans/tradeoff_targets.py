"""Which targets a gap names, per kind. The selection half of the enumeration, and no arithmetic.

Separated from the offers for the reason the wording is: this decides WHO a concession could act on,
the enumerator decides what each would recover, and neither can change the other. A gap carries at
most an Area and a deadline, so every one of these turns what a shortfall renders back into the
resolved rows a concession has to name.

Each is stated against the check that raised the gap, because that is what makes a target applicable
rather than merely present:

*A demand's own tasks* are matched on the Area and the deadline the demand was grouped by, not on
the titles the shortfall renders: two tasks may share a title and only one may be due then.

*The work that competed with a floor* is every OTHER Area's deadline-bearing work, because that
check compares one reservation against what its Area may claim after the other Areas' demands. Its
own Area's work is not competition: a block placed for its own task lands in it and satisfies the
floor.

*The floors a deadline gap honored* are matched through the one function that spells the phrase. A
shortfall carries no identifier for them, and a floor with room after the deadline took nothing from
the window, so the honored list is the record of which ones to offer at all.

*The task a packing failure names* is matched by title, which is the only handle that gap leaves: it
is raised against a candidate the solver could not place rather than against a grouped demand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.feasibility import floor_honored

if TYPE_CHECKING:
    from syncr_domain.feasibility import Shortfall
    from syncr_solver.inputs import AreaBudget, EligibleTask, SolveInputs


def due_at(shortfall: Shortfall, inputs: SolveInputs) -> tuple[EligibleTask, ...]:
    """The tasks that make up the demand this gap was raised against.

    **This can be empty while the demand is not.** Eligibility nets immovable placements wherever
    they sit and the demand nets only those before the deadline, so a task covered by a pin AFTER
    its own deadline has a demand and no eligible row, and neither task-targeted kind can name it.
    The enumerator's module docstring carries the consequence.
    """
    return tuple(
        task
        for task in inputs.eligible_tasks
        if task.area_id == shortfall.area_id and task.deadline == shortfall.deadline
    )


def competing_with(shortfall: Shortfall, inputs: SolveInputs) -> tuple[EligibleTask, ...]:
    """The deadline-bearing work of every OTHER Area, which is what took this floor's capacity."""
    return tuple(
        task
        for task in inputs.eligible_tasks
        if task.area_id != shortfall.area_id and task.deadline is not None
    )


def named_by(shortfall: Shortfall, inputs: SolveInputs) -> tuple[EligibleTask, ...]:
    """The tasks a packing failure names, narrowed to the shortfall's Area where it names one."""
    return tuple(
        task
        for task in inputs.eligible_tasks
        if task.title in shortfall.against and shortfall.area_id in (None, task.area_id)
    )


def honored_floors(shortfall: Shortfall, inputs: SolveInputs) -> tuple[AreaBudget, ...]:
    """The floors this gap honored, which are the ones breaching would recover time from."""
    return tuple(
        area
        for area in inputs.areas
        if floor_honored(label=area.name, reserved_minutes=area.floor_reservation_minutes)
        in shortfall.honoring
    )


def the_areas_own(shortfall: Shortfall, inputs: SolveInputs) -> tuple[AreaBudget, ...]:
    """The floor this gap is about, which is the one the user would be breaching."""
    return tuple(area for area in inputs.areas if area.area_id == shortfall.area_id)
