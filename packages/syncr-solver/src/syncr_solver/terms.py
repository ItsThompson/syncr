"""The seven raw measurements the objective weighs, one function each.

Each returns a **dimensionless non-negative ratio** rather than minutes or a count, so the seven
weights are comparable relative importances and a share of the total is a percentage a panel can
render. 1.0 means the whole of what the term measures went wrong.

``deadline_risk``, ``staleness`` and ``churn`` are bounded by 1 by construction. The other three,
``budget_deviation``, ``fragmentation`` and ``context_switch``, can exceed it, because an Area
allocated far past its target and a plan cut into many pieces are both worse than the whole of what
the term measures: a clamp there would flatten the gradient the search climbs. Measured on a
210-block week at version 1's weights, the three sit at 0.62, 0.14 and 0.003 of their own units.

## Every term is zero on a week with nothing in it

Each denominator is a figure the week itself carries, and each is guarded at zero: no eligible
task with a deadline, no Area target, no block carrying an Area, no due occurrence, no
discretionary time. A term with nothing to measure costs nothing, so an empty week has a total
of zero and no dominant term.

## Which figures are netted, and which are gross

Stated here once because two fields of one producer net different sets, and reading the wrong
one is the fault this epic has paid most for.

``deadline_risk`` compares ``EligibleTask.remaining_minutes`` against the minutes placed toward
it, and **both sides net the started blocks and the pins**, because the demand arrives net of
them. ``fragmentation`` measures each piece against that same demand, so it nets the same set for
the same reason.

``budget_deviation`` compares ``AreaBudget.target_minutes`` against the minutes placed in that
Area, and **neither side nets anything**: the target is gross because it is a reporting figure
rather than a reservation.

``churn`` nets no minutes at all, because it counts moves. The other three measure the plan
against itself, so no producer figure reaches them.

``AreaBudget.floor_minutes`` and ``floor_reservation_minutes`` are read by NOTHING here. A floor
is a hard constraint, H9, and charging an objective term for the same requirement would price it
twice. ``duration_multiplier`` is not reachable from a
:class:`~syncr_solver.weights.WeightSet` at all.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from math import sqrt
from typing import TYPE_CHECKING, Final

from syncr_domain.plan import PlanError
from syncr_solver.preferred import MISFIT_MAX, ResolvedPreferences, misfit_of
from syncr_solver.reading import gap_minutes, in_start_order, shortest_placeable_minutes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identity import BlockId
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import EligibleTask
    from syncr_solver.reading import PlanReading
    from syncr_solver.weights import WeightSet

# How sharply deadline risk rises as the unplaced share of a demand grows. Above one, so the
# curve is convex: a demand ten percent short costs a hundredth of one wholly unplaced, which is
# what gives the term practical dominance at the tight end while leaving `budget_deviation` able
# to win where slack still exists. A rigid ordering would make a budget deviation of any size
# invisible next to a deadline risk of any size, and that is not how the user reasons.
DEADLINE_RISK_EXPONENT: Final = 2.0

# How sharply churn rises through the point the user tolerates. The same exponent as the deadline
# curve and the same reason: below the tolerance the moves are absorbed cheaply, and around it the
# cost climbs an order of magnitude in one octave.
#
# **The curve SATURATES rather than growing without bound, and that is load-bearing.** Churn is a
# term in this objective rather than a rival engine: combined with the proposal-approval gate the
# user gets an optimal re-solve that is never surprising, and a minimal-diff engine would deliver a
# worse plan to avoid a change the gate already makes safe. An unbounded curve IS that engine.
# Measured on a 210-block week, an unbounded square of the same ratio charged 4900 against a total
# of 7.8 for the other six, which is a hard constraint wearing a weight's clothing.
CHURN_KNEE_EXPONENT: Final = 2.0

# Below this, one over the ratio squared overflows a float, and the cost is zero to a float's own
# precision anyway. Derived from the float's own range rather than chosen, so the arithmetic is
# total over every tolerance the weight set admits.
_CHURN_KNEE_FLAT: Final = sqrt(sys.float_info.max)


class StalenessInput(StrEnum):
    """The two complaints the staleness term carries, named so the split can say which dominated.

    Two members and no third. A term with two inputs has two names; a member for "neither" would
    be a name for the absence of a cost, which the split reports as nothing instead.
    """

    CADENCE = "cadence"
    ROTATION = "rotation"


@dataclass(frozen=True, slots=True, kw_only=True)
class StalenessSplit:
    """The two inputs of the staleness term, and which of them dominated.

    **One term with two inputs, not two terms.** An overdue cadence item and a rotation that has
    not advanced are the same complaint, that something is falling behind, and splitting them
    doubles a weight the learning layer must fit from sparse data.

    **Which input dominated is carried by the objective BREAKDOWN, and the reason record does not
    name it.** The ``dominant`` clause names the TERM, ``staleness``, and holds no field an input
    could go in, so a block's record says the week is falling behind and not which half of it is.
    The breakdown reaches a plan revision as its seven costs alone, so the split does not survive
    that row either: it is readable for as long as the solve that computed it and no longer.

    The two figures PARTITION the due occurrences rather than overlapping: an occurrence's
    content comes from a rotation cursor or it does not, so no occurrence is in both and the
    share below cannot count one twice.
    """

    cadence_minutes: int = 0
    rotation_minutes: int = 0
    due_minutes: int = 0

    def share(self) -> float:
        """The fraction of this week's due occurrences the plan leaves unplaced."""
        if self.due_minutes <= 0:
            return 0.0
        return (self.cadence_minutes + self.rotation_minutes) / self.due_minutes

    def dominant(self) -> StalenessInput | None:
        """Which input carried more of the cost, or nothing because neither carried any.

        A tie goes to the cadence, which is the order the two are declared in. Nothing to report
        is reported as nothing rather than as a name at zero: a split naming a dominant input
        that cost nothing states something no arithmetic here computed.
        """
        if self.cadence_minutes == self.rotation_minutes == 0:
            return None
        if self.cadence_minutes >= self.rotation_minutes:
            return StalenessInput.CADENCE
        return StalenessInput.ROTATION


def deadline_risk(reading: PlanReading) -> float:
    """How far this plan's placements fall short of what each deadline demands, nonlinearly.

    Reads ``EligibleTask.deadline`` and ``EligibleTask.remaining_minutes``, which are the
    SOLVER's quantities. It does NOT read ``deadline_demands``: that field is the probe's, it
    nets every placement rather than the immovable ones, and it is scoped per deadline. Reading
    it here would place a task at half its size and report no shortfall, because both sides would
    agree.

    A demand-weighted mean of the per-demand pressures, so four hours short of a four-hour task
    weighs more than fifteen minutes short of a fifteen-minute one, and so placing any further
    minute before any deadline lowers the term. A maximum would not move when a second deadline
    went unmet, and a sum would leave the term unbounded in the number of tasks rather than in
    how much of the work is late.
    """
    demanded = 0
    charged = 0.0
    for task in reading.inputs.eligible_tasks:
        if task.deadline is None or task.remaining_minutes <= 0:
            continue
        placed = reading.placed_toward(task.binding, before=task.deadline)
        pressure = max(0, task.remaining_minutes - placed) / task.remaining_minutes
        demanded += task.remaining_minutes
        charged += task.remaining_minutes * pressure**DEADLINE_RISK_EXPONENT
    if demanded == 0:
        return 0.0
    return charged / demanded


def budget_deviation(reading: PlanReading) -> float:
    """How far each Area's allocation sits from its target for the week, in either direction.

    Absolute, because over-serving an Area is a deviation as much as under-serving it is: an hour
    the budget gave to Study and the plan gave to Fitness is wrong twice.

    Both sides are GROSS. ``target_minutes`` is net of nothing because it is a reporting figure
    rather than a reservation, so the minutes it is compared against are every minute the plan
    places in that Area. ``AreaBudget.placed_minutes`` is deliberately not added: it counts the
    same placements this plan's own blocks are, and adding the two would charge one Area for its
    week twice. That is the fault class this epic has found at five sites.

    An Area the inputs declare no budget for is not measured, because it states no target for a
    placement to deviate from.
    """
    targets = tuple((area.area_id, area.target_minutes) for area in reading.inputs.areas)
    total = sum(target for _, target in targets)
    if total <= 0:
        return 0.0
    gap = sum(abs(reading.minutes_in(area_id) - target) for area_id, target in targets)
    return gap / total


def time_of_day_misfit(reading: PlanReading, weights: WeightSet) -> float:
    """How badly this plan's placements sit against when their work should happen.

    **One term, four components, one weight.** The components, their scales and the resolution of
    whose preference applies are all in :mod:`syncr_solver.preferred`. A user's stated window and
    their observed behaviour are different claims and both count.

    Neither strength can leave a block unscheduled, because this is a cost and not a constraint:
    H5 was withdrawn for exactly that reason, so there is no rule to refuse a placement outside a
    window and the worst a block can suffer here is the full component.

    Minute-weighted, so a two-hour block in the wrong part of the day costs more than a
    fifteen-minute one, and divided by the most the components could charge, so the term stays a
    fraction whatever the plan holds.
    """
    preferences = ResolvedPreferences(reading.inputs.preferences)
    minutes = 0
    charged = 0.0
    for placed in reading.area_blocks():
        minutes += placed.minutes()
        charged += placed.minutes() * misfit_of(
            placed.block.interval,
            binding=placed.block.binding,
            area_id=placed.area_id,
            hour=reading.local_hour(placed.block.interval.start),
            preferences=preferences,
            weights=weights,
        )
    if minutes == 0:
        return 0.0
    return charged / (minutes * MISFIT_MAX)


def fragmentation(reading: PlanReading) -> float:
    """What this plan's splitting costs: pieces below their ideal, and gaps nothing can use.

    Two components over disjoint sets of minutes. The first is measured over the time the plan
    PLACES, as how far each piece falls below the ideal session length its preference states. The
    second is measured over the time the plan LEAVES, as gaps too short for any content the week
    holds. No minute is in both, because one is claimed by an Area's block and the other is not.

    **It never overrides a minimum chunk.** The ideal is a preference and the minimum is H7, so
    the charge only ever grows as a piece gets shorter: an ideal below a minimum charges a piece
    at the minimum nothing at all, and no arrangement of pieces is ever made cheaper by cutting
    one smaller. So the term cannot push a placement below the length its content declares.

    The ideal is also capped by what the demand still owes, so a task with forty minutes left is
    not charged for failing to fill a ninety-minute session it has no work for.
    """
    denominator = reading.discretionary_minutes()
    if denominator <= 0:
        return 0.0
    preferences = ResolvedPreferences(reading.inputs.preferences)
    deficit = sum(
        _split_deficit(task, preferences, reading) for task in reading.inputs.eligible_tasks
    )
    return (deficit + _unusable_minutes(reading)) / denominator


def churn(reading: PlanReading, weights: WeightSet) -> float:
    """How far this plan has moved from the one the user approved, shaped by their tolerance.

    Measured against the last APPROVED revision, which the baseline names. "The last plan the
    user saw" is not a persistable definition; "the week I signed off" already is, and it is
    stored with the instant of assent.

    **A week with no approved plan has zero churn**, and the baseline states why rather than the
    term silently comparing against a proposal nobody assented to.

    Moves and drops, counted as blocks and paired on the derived block id. An ADDITION is not
    churn: nothing the user approved was rearranged by placing something new beside it, which is
    the same reading that lets a diff of additions alone apply without assent. The two sets are
    disjoint, because a block is either in both documents or in one.

    ``churn_tolerance`` shapes the term and the churn WEIGHT scales it. Below the tolerance the
    moves are absorbed cheaply, at it they cost half the term's unit, and past it the cost climbs
    toward the whole of it without ever passing it. That last part is why the curve saturates: see
    :data:`CHURN_KNEE_EXPONENT`.
    """
    baseline = reading.inputs.churn_baseline
    approved = baseline.document
    if approved is None:
        return 0.0
    _require_one_week(reading.plan, approved)
    before = approved.blocks_by_id()
    after = reading.plan.blocks_by_id()
    return _knee(_moves(before, after) / weights.churn_tolerance)


def _knee(ratio: float) -> float:
    """A cost that is cheap below one, half at one, and approaches one above it.

    Written as one over one plus the inverse raised to the exponent, rather than as the ratio raised
    to it over one plus the same. The two are algebraically equal and only this one is total: the
    direct form overflows a float at a ratio of about 2e202, which a tolerance of a two-hundredth of
    a move reaches on an ordinary week.
    """
    if ratio <= 0:
        return 0.0
    inverse = 1.0 / ratio
    if inverse >= _CHURN_KNEE_FLAT:
        return 0.0
    return 1.0 / (1.0 + float(inverse**CHURN_KNEE_EXPONENT))


def context_switch(reading: PlanReading, weights: WeightSet) -> float:
    """What this plan's Area changes cost, charged against the room it leaves between them.

    ``context_switch_cost`` is the price of one change, in MINUTES, and the gap the schedule
    already leaves between the two blocks absorbs it: two blocks of different Areas back to back
    cost the whole price, and a gap at least as long as the price costs nothing. That is what
    makes the price a unit rather than a second scale, and it is why the price and the
    ``context_switch`` weight are not collapsible into their product: at any pair with a gap,
    doubling the price is not the same as doubling the weight.

    A night's sleep therefore needs no rule of its own. It leaves hours of gap, which absorbs any
    price, so nothing has to say that a day boundary is not a context switch.

    Adjacency is over the blocks that carry an Area, in span order. The frame and the imported
    commitments carry none: one defines how much time exists and the other is time the product
    does not own, and neither is an Area the user changed to.
    """
    denominator = reading.discretionary_minutes()
    if denominator <= 0:
        return 0.0
    ordered = in_start_order(reading.area_blocks())
    charged = sum(
        max(0.0, weights.context_switch_cost - gap_minutes(earlier, later))
        for earlier, later in pairwise(ordered)
        if earlier.area_id != later.area_id
    )
    return charged / denominator


def staleness(reading: PlanReading) -> StalenessSplit:
    """What this plan leaves falling behind: overdue cadence items, and a stuck rotation.

    Both figures are minutes of due occurrences the plan places nowhere. An occurrence whose
    content came from the rotation cursor is the rotation half, and every other one is the
    cadence half; a rotation only advances when its occurrence is done, so an unplaced one is
    exactly a rotation that has not advanced.

    Made-up occurrences need no separate reading. Debt is applied before these inputs are built,
    so a missed occurrence is already among them and is already counted at its own size.

    The whole split is returned rather than one number, so the breakdown can name which input
    dominated without the term being two terms.
    """
    placed = {block.binding for block in reading.plan.blocks}
    owed = {StalenessInput.CADENCE: 0, StalenessInput.ROTATION: 0}
    due = 0
    for occurrence in reading.inputs.habit_occurrences:
        # The smallest legal length, because that is the least of the occurrence the week owes.
        # An elastic occurrence sized up is the objective's business elsewhere.
        minutes = occurrence.duration.min_minutes
        due += minutes
        if occurrence.binding in placed:
            continue
        which = (
            StalenessInput.ROTATION if occurrence.variant is not None else StalenessInput.CADENCE
        )
        owed[which] += minutes
    return StalenessSplit(
        cadence_minutes=owed[StalenessInput.CADENCE],
        rotation_minutes=owed[StalenessInput.ROTATION],
        due_minutes=due,
    )


def _split_deficit(
    task: EligibleTask, preferences: ResolvedPreferences, reading: PlanReading
) -> int:
    """How far each piece placed for this task falls below the session length it prefers."""
    ideal = preferences.ideal_session_minutes(task.binding, task.area_id)
    if ideal is None or task.remaining_minutes <= 0:
        return 0
    # Capped by what is left to place, so a task with less work than one ideal session is not
    # charged for the session it has no work to fill.
    capped = min(ideal, task.remaining_minutes)
    return sum(max(0, capped - piece) for piece in reading.chunks_toward(task.binding))


def _unusable_minutes(reading: PlanReading) -> int:
    """Free discretionary minutes in gaps too short for anything the week holds.

    Measured over the gaps rather than as a residual, so the figure is minutes that really exist
    and it is bounded by the denominator it is divided by.
    """
    shortest = shortest_placeable_minutes(reading.inputs)
    if shortest <= 0:
        return 0
    return sum(
        member.total_minutes() for member in reading.free if member.total_minutes() < shortest
    )


def _moves(before: Mapping[BlockId, Block], after: Mapping[BlockId, Block]) -> int:
    """How many of the approved plan's blocks this one moved or dropped.

    Disjoint by construction: a block of the approved plan is in this one at some span, or it is
    not in it at all.
    """
    moved = sum(
        1
        for block_id, block in before.items()
        if block_id in after and after[block_id].interval != block.interval
    )
    dropped = sum(1 for block_id in before if block_id not in after)
    return moved + dropped


def _require_one_week(plan: PlanDocument, baseline: PlanDocument) -> None:
    """Two documents of one week, because a block id is derived from the week it belongs to.

    Refused rather than compared. Ids from two weeks never pair, so the comparison would report
    every block of the baseline as dropped and every block of the plan as an addition: a maximal
    churn on two plans that may be identical.
    """
    if plan.iso_week != baseline.iso_week:
        raise PlanError(
            f"churn compares a plan for {plan.iso_week} against an approved plan for "
            f"{baseline.iso_week}: a block's id is derived from its week, so no block of one "
            "would pair with any block of the other and every one would read as dropped"
        )
