"""Folding approved concessions into the resolved quantities. One code path, run last.

A concession is a decision the user made about a hard week, and the whole of its effect is that
some resolved figure is different from what the stored declarations say. So folding is a
**post-pass over the already-resolved fields** rather than a step inside the pipeline: every
quantity a concession changes is computed before this runs, which is what makes "what does this
concession touch" answerable by reading one function.

**Stored concessions and an unpersisted candidate travel the same path.** A tradeoff being
evaluated is an argument to the assembly rather than a row, so requesting one persists nothing,
and the candidate joins the stored list before this runs. A second code path for the candidate is
how the two would come to apply a concession differently.

**Three of the four kinds touch TWO fields, because two consumers read two quantities.** A kind
that touched one of a pair would leave its concession half applied, and each half-application has
its own user-visible failure:

``drop_item`` removes the task from eligibility AND every demand naming it. Without the second,
the probe keeps demanding work for a task nothing will schedule, so a phantom shortfall persists
and the task stays marked at risk.

``accept_partial`` clears the task's deadline AND removes every demand naming it. Without the
first, the panel goes quiet while the objective still strains against the deadline the user
excused, because deadline risk reads the eligibility and not the demand.

``breach_floor`` lowers the Area's declared floor, floor minutes, AND floor reservation. Without
one, a reader sees the declaration drift from the resolved constraint or the probe reports the
same gap after the user approves the breach.

``reduce_routine`` shortens the frame occurrence on each named date, and nothing further. The
frame is one field.

A concession is unique per week, kind, and target, which the storage index enforces, so approving it
twice does not apply it twice. That covers stored rows only: a candidate being evaluated is an
argument rather than a row, so a candidate and a stored concession on one kind and target both
apply. :func:`fold` carries the whole statement, including what that means for the figure.

**``delta_minutes`` is an INCREMENT, not an absolute figure.** It is how much this one concession
lowers the figure it names, and it is computed against the week as it stands: the enumerator reads
an already-folded assembly, so a second breach of a floor that already carries one is offered
against what is left of it. Compounding is therefore correct arithmetic rather than a defect, and
the alternative reading would make one column mean two things depending on whether a stored
concession exists.

**What makes the pair unreachable today is OFFER-TIME suppression, not this pass.** The enumerator
drops any kind and target the assembly already carries, and the request path refuses a concession it
did not offer, so no candidate reaching this fold shares a kind and target with a stored row.
Nothing here prevents it. A caller that folds a candidate against a concession stored AFTER the
request was made would compound the two, which becomes reachable once a worker reads a candidate off
an operation and an approval can land between the two. Whether a superseded solve's follow-up
carries its candidate forward is the coordinator's design, and that is where the interleaving has to
be answered.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, assert_never

from syncr_api.plans.materialization import reduced_frame_entry
from syncr_domain.identity import date_occurrence_key
from syncr_domain.plan import AdjustmentKind

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_api.plans.demand import TaskDemand
    from syncr_solver.inputs import AreaBudget, EligibleTask, FrameEntry, WeekAdjustment


@dataclass(frozen=True, slots=True)
class Concessions:
    """The four resolved collections a concession can change, before and after the fold.

    One shape in and one shape out, so the pass is a total function of the fields it modifies
    rather than four mutations a caller has to apply in the right order.
    """

    frame: tuple[FrameEntry, ...]
    eligible_tasks: tuple[EligibleTask, ...]
    demands: tuple[TaskDemand, ...]
    areas: tuple[AreaBudget, ...]


# What each kind's approval modifies, named as the ``SolveInputs`` field it lands in, and dotted
# with the member field where the collection keeps its members and changes one of their values.
#
# Declared rather than described, because the defect this table exists against was a row of prose
# naming one field of a pair: three of the four kinds touch two quantities, since the solver's
# reading and the probe's reading of one concession are separate fields. A test folds one
# concession of each kind through a real assembly, observes which fields moved, and compares the
# observation against this table in both directions.
#
# ``preferences`` is the entry no prose table names. Preferences are resolved over the FOLDED
# eligibility, so a dropped task takes its resolved window with it, which is right: a task nothing
# will schedule this week needs no window.
FOLDED_FIELDS: Final[Mapping[AdjustmentKind, frozenset[str]]] = {
    AdjustmentKind.DROP_ITEM: frozenset({"eligible_tasks", "deadline_demands", "preferences"}),
    AdjustmentKind.REDUCE_ROUTINE: frozenset({"frame.interval"}),
    AdjustmentKind.BREACH_FLOOR: frozenset(
        {
            "areas.declared_floor_minutes",
            "areas.floor_minutes",
            "areas.floor_reservation_minutes",
        }
    ),
    AdjustmentKind.ACCEPT_PARTIAL: frozenset({"eligible_tasks.deadline", "deadline_demands"}),
}


def fold(adjustments: Sequence[WeekAdjustment], into: Concessions) -> Concessions:
    """``into`` with every concession applied, in the order the concessions arrive.

    Order does not change the result: each kind targets one entity, each pair of fields is changed
    by one kind, and successive clamped subtraction commutes.

    **Two concessions on one kind and one target COMPOUND.** The storage index makes that
    unreachable for two stored concessions, and it does not cover a candidate being evaluated,
    because a candidate is an argument rather than a row. So a stored breach of 60 minutes plus a
    candidate breach of 120 lowers a 300-minute floor to 120, because each ``delta_minutes`` is an
    increment against the figure as it stands rather than an absolute target. The module docstring
    states why that is the reading, and why the enumerator never offers the pair.
    """
    folded = into
    for adjustment in adjustments:
        folded = _apply(adjustment, folded)
    return folded


def _apply(adjustment: WeekAdjustment, into: Concessions) -> Concessions:
    match adjustment.kind:
        case AdjustmentKind.DROP_ITEM:
            return _dropped(into, task_id=adjustment.target_id)
        case AdjustmentKind.ACCEPT_PARTIAL:
            return _deadline_excused(into, task_id=adjustment.target_id)
        case AdjustmentKind.BREACH_FLOOR:
            return _floor_breached(
                into, area_id=adjustment.target_id, by_minutes=adjustment.delta_minutes
            )
        case AdjustmentKind.REDUCE_ROUTINE:
            return _routine_reduced(into, adjustment=adjustment)
        case _:  # pragma: no cover - unreachable while AdjustmentKind has four members
            assert_never(adjustment.kind)


def _dropped(into: Concessions, *, task_id: UUID) -> Concessions:
    """The task leaves eligibility, and every demand naming it goes with it.

    ``Task.status`` is untouched, because dropping a task permanently is a different act with a
    different meaning: this concession is about one week.
    """
    return replace(
        into,
        eligible_tasks=tuple(
            task for task in into.eligible_tasks if task.binding.entity_id != task_id
        ),
        demands=tuple(demand for demand in into.demands if demand.task_id != task_id),
    )


def _deadline_excused(into: Concessions, *, task_id: UUID) -> Concessions:
    """The task keeps its work and loses its deadline, on both quantities that carry one.

    Clearing the deadline on eligibility is what stops the objective's deadline risk straining
    against an excused date, and dropping the demands is what stops the panel reporting a
    shortfall for it. The stated effect of this concession is false without both.
    """
    return replace(
        into,
        eligible_tasks=tuple(
            replace(task, deadline=None) if task.binding.entity_id == task_id else task
            for task in into.eligible_tasks
        ),
        demands=tuple(demand for demand in into.demands if demand.task_id != task_id),
    )


def _floor_breached(into: Concessions, *, area_id: UUID, by_minutes: int | None) -> Concessions:
    """All three of the Area's floor quantities fall by the approved minutes, clamped at zero.

    A concession that stated no minutes lowers nothing. The size of a breach is what the user
    approved, so inferring one here would be the assembler choosing how far to breach a floor.

    A figure at or below zero lowers nothing either, and that guard is not defensive: subtracting a
    negative would RAISE the floor, so a concession whose whole meaning is to relax a hard
    constraint would tighten one. No production path writes the column yet and it carries no check
    constraint, so the fold is where the absurd state stops.
    """
    if by_minutes is None or by_minutes <= 0:
        return into
    return replace(
        into,
        areas=tuple(
            replace(
                budget,
                declared_floor_minutes=max(0, budget.declared_floor_minutes - by_minutes),
                floor_minutes=max(0, budget.floor_minutes - by_minutes),
                floor_reservation_minutes=max(0, budget.floor_reservation_minutes - by_minutes),
            )
            if budget.area_id == area_id
            else budget
            for budget in into.areas
        ),
    )


def _routine_reduced(into: Concessions, *, adjustment: WeekAdjustment) -> Concessions:
    """Each named date's occurrence of that routine runs shorter, never below its floor.

    A reduction names local dates and a frame entry is keyed by one, so the two are paired
    through the one derivation of that key rather than by formatting a date here.
    """
    reductions = {date_occurrence_key(on): minutes for on, minutes in adjustment.reductions.items()}
    return replace(
        into,
        frame=tuple(
            reduced_frame_entry(entry, reduction_minutes=reductions[entry.occurrence_key])
            if entry.routine_id == adjustment.target_id and entry.occurrence_key in reductions
            else entry
            for entry in into.frame
        ),
    )
