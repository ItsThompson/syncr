"""Tradeoff enumeration: what could close each gap, what each would recover, and nothing chosen.

The panel's other half. The probe proves a week impossible and quantifies the gap; this turns
every gap into the concessions that could close it, states what each recovers, and stops. **syncr
never selects one.** The user may be tired and accept partial delivery, or cut sleep, or drop
something, and that decision is theirs: this module returns a list, mutates nothing, and reads no
clock.

## What each shortfall kind can be answered with

Applicability is decided from the arithmetic the check performed, so a kind is offered only where
approving it would move the figure the check compared.

Four gaps, and what each can be answered with.

*The floors against the week.* A breach of each floor that still reserves capacity, and a reduction
of each elastic routine. The check compares the reservations against free capacity, so lowering one
or raising the other closes it.

*A demand against its deadline.* Dropping or excusing each task the demand names, a breach of each
floor the shortfall HONORED, and a reduction over the nights before the deadline. The check compares
the demand against the capacity its Area has before the deadline, less the other Areas' floors that
could not wait until after it.

*A floor against its own Area.* A breach of that floor, dropping or excusing the deadline-bearing
work elsewhere that competed for the same capacity, and a reduction. The check compares one
reservation against what its Area may claim after the other Areas' demands.

*A chunk against the shape of what is left.* Dropping or excusing the task named, and a reduction,
which lengthens the windows. This is the packing failure no total can measure and only an attempted
placement can find.

**A breach is offered for a deadline gap only when the shortfall honored that floor.** The probe
reserves the part of another Area's floor that cannot fit after the deadline, so a floor with room
to spare later took nothing from the window and breaching it would recover nothing. The honored
list is the record of which floors did take capacity, and it carries no identifier, so the phrase
is matched through the one function that spells it.

## What a tradeoff states it recovers

| Kind | Recovers |
|---|---|
| ``drop_item``, ``accept_partial`` | the gap, capped by the work that task still holds |
| ``breach_floor`` | the gap, capped by what that Area's floor still reserves |
| ``reduce_routine`` | the sum of the reductions it names |

The reduction figure is the minutes handed back to the week, which is capacity unless another
commitment already covered that span.

**Three bounds on the stated figure, each measured rather than argued.** A figure is an UPPER bound
on the gap movement in each case, never a lower one, so a row can promise more than approving it
delivers and never less.

*A breach against a DEADLINE gap can state more than that gap can fall by.* The deadline check does
not subtract the reservation: it subtracts ``max(claimed, reserved - absorbed_later)``, where
``absorbed_later`` is the free capacity after the deadline and ``claimed`` is what that Area's
earlier deadlines already took. So lowering the reservation by ``delta`` lowers the competition by
at most ``early - claimed``, and by nothing once ``claimed >= early``. A floor with room after the
deadline took nothing from the window, which the honored list already filters for; a floor with only
SOME of itself early is not filtered, and the figure is capped at the whole reservation. Against the
other two gap kinds the figure is exact, because both compare a reservation directly.

*A demand naming several tasks has no per-task split on a solve input.* The probe's demand is one
figure per deadline and Area, because the tasks compete for the same capacity. So excusing one of
three tasks closes part of the gap and the offer states the whole of it. One task per demand is
the ordinary case and is exact.

*The task cap reads ELIGIBILITY's figure*, which nets immovable placements only, while the gap was
computed from the demand, which nets every placement before the deadline. The two differ for a task
carrying an unpinned future block before its deadline, and there the stated figure can exceed what
the gap actually falls by.

Closing any of the three needs the same shape of change, a per-contributor figure carried on the
shortfall, so it is one decision rather than three.

## What it never does

It selects nothing, persists nothing, and mutates nothing: the tradeoff a user picks becomes a
candidate concession the assembly folds in, and the fold is the only thing that changes a figure.
It offers no concession the week already holds, because a concession already applied is shown on
the panel as an applied concession instead of being offered a second time. And it mints no
identifier: an offer is a value derived from one assembly, so two enumerations of one assembly are
equal, which they could not be if a candidate's identity were minted here.

**One gap shape is answered with nothing, and it is not a valid state.** A deadline demand whose
task has no eligible row cannot be dropped or excused, because both need the task's identity and
only eligibility carries it: a task whose whole estimate is covered by an immovable placement AFTER
its deadline has a demand and no eligibility. Where the week also has no elastic routine and no
honored floor, such a gap is offered nothing at all. It is logged rather than left silent: a panel
reporting a gap with no button is otherwise invisible outside the request that rendered it.

The warning sits inside the enumeration rather than at a call site, so it fires wherever this runs
and every caller inherits it. Today that is the tradeoff request path only, which means it fires
when a user asks for a concession against some OTHER gap on a week that also holds an unanswerable
one, and not on a render: no route serializes these yet. Once the panel's own read lands it needs no
change here to be covered, which is why the log belongs here and not in the service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, assert_never

from syncr_api.plans import tradeoff_labels as labels
from syncr_api.plans import tradeoff_nights as nights
from syncr_api.plans import tradeoff_targets as targets
from syncr_common.logging import get_logger
from syncr_domain.feasibility import ShortfallKind, Tradeoff
from syncr_domain.plan import AdjustmentKind
from syncr_solver.inputs import WeekAdjustment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_domain.feasibility import Shortfall, Verdict
    from syncr_domain.identifiers import WeekAdjustmentId
    from syncr_domain.intervals import Instant
    from syncr_domain.zones import Date
    from syncr_solver.inputs import AreaBudget, EligibleTask, SolveInputs

# What a request names, and what the storage index is keyed by: one concession per kind and
# target. Two offers sharing it are one offer, and the larger recovery is the one kept.
type OfferedConcession = tuple[AdjustmentKind, UUID]

_log = get_logger("syncr.plans")


@dataclass(frozen=True, slots=True, kw_only=True)
class Offer:
    """One tradeoff on offer, and the concession approving it would apply.

    Two readings of one decision, held together so they cannot diverge: ``tradeoff`` is what the
    panel renders and what crosses the wire, and the rest is what the fold would read. A request
    names a kind and a target and the offer supplies the figures, which is what stops a caller
    asking to reduce a routine below its own floor or to breach a floor by an amount nothing
    offered.
    """

    tradeoff: Tradeoff
    reductions: Mapping[Date, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reductions", dict(self.reductions))

    @property
    def concession(self) -> OfferedConcession:
        """The kind and target a request names to ask for this one."""
        return (self.tradeoff.kind, self.tradeoff.target_id)

    @property
    def recovers(self) -> int:
        """The minutes this offer states it recovers, as an UPPER bound on the gap movement.

        Positive for everything :func:`offered_tradeoffs` returns, and never less than what
        approving the concession delivers: the module docstring states the three cases where it can
        be more, and why that is the safe direction for a panel to be wrong in.
        """
        return self.tradeoff.delta_minutes or 0

    def as_candidate(self, *, adjustment_id: WeekAdjustmentId) -> WeekAdjustment:
        """The unpersisted concession an assembly folds in to evaluate this offer.

        The identity is supplied rather than minted here, because an offer is derived from an
        assembly and a value that can be minted makes two enumerations of one assembly unequal.
        """
        return WeekAdjustment(
            adjustment_id=adjustment_id,
            kind=self.tradeoff.kind,
            target_id=self.tradeoff.target_id,
            reductions=self.reductions,
            delta_minutes=self.tradeoff.delta_minutes,
        )


def offered_tradeoffs(inputs: SolveInputs, verdict: Verdict) -> tuple[Offer, ...]:
    """Every concession that could close a gap in ``verdict``, over the assembly it was taken on.

    Deterministic: shortfalls in the verdict's own order, then the kinds in the order the product
    lists them, then targets in the order the assembly resolved them. Nothing is selected and
    nothing is written.

    One offer per kind and target, because that is what a concession is keyed by. Where two gaps
    offer the same one, the LARGER recovery is kept: the concession has to close the larger gap it
    was offered against, and stating the smaller figure would understate what the user is
    approving.

    A gap this can answer with nothing is logged rather than passed over, wherever this runs: the
    module docstring names the one shape that reaches it, and the panel's silence is otherwise
    visible only to the request that rendered it.
    """
    applied = {(adjustment.kind, adjustment.target_id) for adjustment in inputs.adjustments}
    offers: dict[OfferedConcession, Offer] = {}
    for shortfall in verdict.shortfalls:
        answered = _against(shortfall, inputs)
        if not answered:
            _log.warning(
                "plans.tradeoff.gap_unanswered",
                iso_week=str(inputs.iso_week),
                shortfall_kind=shortfall.kind.value,
                minutes=shortfall.minutes,
                area_id=None if shortfall.area_id is None else str(shortfall.area_id),
            )
        for offer in answered:
            if offer.concession in applied:
                continue
            held = offers.get(offer.concession)
            if held is None or held.recovers < offer.recovers:
                offers[offer.concession] = offer
    return tuple(offers.values())


def _against(shortfall: Shortfall, inputs: SolveInputs) -> tuple[Offer, ...]:
    """The offers one gap can be answered with, in the order the product lists the kinds.

    Exhaustive over the shortfall vocabulary rather than defaulting, so a fifth kind is a type
    error here instead of a gap the panel offers nothing against.
    """
    match shortfall.kind:
        case ShortfallKind.FLOORS_EXCEED_CAPACITY:
            return (
                *_reductions(shortfall, inputs, before=None),
                *_breaches(shortfall, of=inputs.areas),
            )
        case ShortfallKind.DEADLINE_CAPACITY:
            due = targets.due_at(shortfall, inputs)
            return (
                *_drops(shortfall, due),
                *_reductions(shortfall, inputs, before=shortfall.deadline),
                *_breaches(shortfall, of=targets.honored_floors(shortfall, inputs)),
                *_excusals(shortfall, due),
            )
        case ShortfallKind.AREA_FLOOR_UNREACHABLE:
            competing = targets.competing_with(shortfall, inputs)
            return (
                *_drops(shortfall, competing),
                *_reductions(shortfall, inputs, before=None),
                *_breaches(shortfall, of=targets.the_areas_own(shortfall, inputs)),
                *_excusals(shortfall, competing),
            )
        case ShortfallKind.MINIMUM_CHUNK_UNPLACEABLE:
            named = targets.named_by(shortfall, inputs)
            return (
                *_drops(shortfall, named),
                *_reductions(shortfall, inputs, before=shortfall.deadline),
                *_excusals(shortfall, named),
            )
        case _:  # pragma: no cover - unreachable while ShortfallKind has four members
            assert_never(shortfall.kind)


def _drops(shortfall: Shortfall, tasks: Sequence[EligibleTask]) -> tuple[Offer, ...]:
    """Taking each task out of this week, which takes its work out with it."""
    return tuple(
        _an_offer(
            AdjustmentKind.DROP_ITEM,
            target_id=task.binding.entity_id,
            label=labels.dropped(title=task.title),
            recovers=_task_recovery(shortfall, task),
        )
        for task in tasks
    )


def _excusals(shortfall: Shortfall, tasks: Sequence[EligibleTask]) -> tuple[Offer, ...]:
    """Excusing each task's deadline, which leaves the work and removes the date.

    A different act from dropping it, against the same gap: the user decides whether the work or
    the deadline is the part they can give up. A task with no deadline has none to excuse.
    """
    return tuple(
        _an_offer(
            AdjustmentKind.ACCEPT_PARTIAL,
            target_id=task.binding.entity_id,
            label=labels.partial_accepted(title=task.title),
            recovers=_task_recovery(shortfall, task),
        )
        for task in tasks
        if task.deadline is not None
    )


def _task_recovery(shortfall: Shortfall, task: EligibleTask) -> int:
    """The gap, capped by the work the task still holds. Never more than either."""
    return min(shortfall.minutes, task.remaining_minutes)


def _breaches(shortfall: Shortfall, *, of: Sequence[AreaBudget]) -> tuple[Offer, ...]:
    """Lowering each Area's floor by what the gap needs, bounded by what the floor still reserves.

    An Area whose floor reserves nothing is not offered: it is already met by what the week holds,
    so there is nothing left to breach and a concession recovering nothing is worse than none.

    **The figure is exact against the two gaps that compare a reservation directly, and an upper
    bound against a deadline gap**, which subtracts the part of the floor that cannot fit after the
    deadline rather than the whole of it, and subtracts nothing further once that Area's earlier
    deadlines have already claimed more. The module docstring states the arithmetic.
    """
    return tuple(
        _an_offer(
            AdjustmentKind.BREACH_FLOOR,
            target_id=area.area_id,
            label=labels.floor_breached(
                name=area.name, minutes=min(shortfall.minutes, area.floor_reservation_minutes)
            ),
            recovers=min(shortfall.minutes, area.floor_reservation_minutes),
        )
        for area in of
        if area.floor_reservation_minutes > 0
    )


def _reductions(
    shortfall: Shortfall, inputs: SolveInputs, *, before: Instant | None
) -> tuple[Offer, ...]:
    """Shortening each elastic routine over the fewest nights that can supply the gap.

    Which nights are eligible and how much each gives up is :mod:`syncr_api.plans.tradeoff_nights`,
    because the distribution is the one part of a tradeoff that a kind and a target cannot state.
    """
    offered: list[Offer] = []
    dates = nights.dates_of(inputs)
    for routine_id, occurrences in nights.by_routine(inputs.frame).items():
        eligible = nights.reducible(occurrences, after=inputs.now, before=before)
        distribution = nights.distributed(shortfall.minutes, over=eligible, dates=dates)
        if distribution is None:
            continue
        offered.append(
            _an_offer(
                AdjustmentKind.REDUCE_ROUTINE,
                target_id=routine_id,
                label=labels.routine_reduced(
                    title=eligible[0].title,
                    minutes_each=distribution.each,
                    nights=list(distribution.reductions),
                ),
                recovers=distribution.recovers,
                reductions=distribution.reductions,
            )
        )
    return tuple(offered)


def _an_offer(
    kind: AdjustmentKind,
    *,
    target_id: UUID,
    label: str,
    recovers: int,
    reductions: Mapping[Date, int] | None = None,
) -> Offer:
    return Offer(
        tradeoff=Tradeoff(kind=kind, label=label, target_id=target_id, delta_minutes=recovers),
        reductions={} if reductions is None else reductions,
    )
