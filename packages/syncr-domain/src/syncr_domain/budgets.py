"""Area budget arithmetic: floors, the proportional remainder, and the two residuals.

A budget is floors plus a share of what remains, never pure percentages. Pure percentages
fail in exactly the wrong week: a heavy meeting week shrinks every wedge proportionally, so
fitness starves precisely when the user is most stressed, while the budget still reports as
met.

```
after_floors      = max(0, discretionary - sum(floor_minutes))
area_target(a)    = floor_minutes(a) + budget_percent(a) x after_floors
oversubscription  = max(0, sum(area_target) - discretionary)
unallocated       = discretionary minutes covered by no block carrying an Area
```

## `unallocated` and `oversubscription` are different quantities

They are routinely confused and they are reported separately.

``unallocated`` is discretionary time that sits in **no block at all**. It is the pie
wedge, the deviation row, and the summary-strip figure, and it means that one thing
everywhere. An unfilled Area slot increases it, and so does an unfilled per-Area recovery
window: both are discretionary time no block claimed, which is exactly what the figure is
for.

Defining it as ``discretionary - sum(area_target)`` is degenerate, which is why it is
computed from interval coverage instead. For a user whose percentages sum to 100 that
expression is exactly zero every week, and for an oversubscribed budget it is negative,
which is not a renderable wedge. Here the figure is the discretionary set minus the covered
set, so it is non-negative by construction rather than by a clamp, and setting percentages
to sum to exactly 100 does not make it zero.

``oversubscription`` is how far Area targets exceed discretionary time, and it is zero when
they fit. Percentages summing past 100 are accepted and reported, never rejected.

## Two clamps, and why each is here

``after_floors`` is clamped at zero. Without the clamp a negative remainder is multiplied
by each percentage and subtracted from that Area's floor, so the floors' own excess cancels
itself out and a budget whose floors alone cannot fit reports no oversubscription at all.

A target is otherwise **gross**: it is netted against nothing and clamped to nothing,
because it is a reporting figure rather than a reservation. That is what lets
``oversubscription`` measure the demand honestly. A week with no discretionary time and no
declared floors therefore reports a zero target for every Area, which is the routines-only
case: routines define how much time exists, so they never appear in Area budget arithmetic.

## Rounding

A share is computed in ``Decimal`` and truncated toward zero. Truncating means the sum of
the rounded targets never exceeds the sum of the exact ones, so rounding cannot invent an
oversubscription that the declared percentages do not describe.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syncr_domain.identifiers import AreaId

MINUTES_PER_HOUR: Final = 60

# A whole percentage share, as `budget_percent` is authored: 25 means a quarter.
_WHOLE_SHARE: Final = Decimal(100)


class BudgetError(DomainError):
    """The declared budget cannot be read as one."""


def floor_minutes(floor_hours: Decimal | None) -> int:
    """Weekly floor hours as whole minutes. An undeclared floor reserves nothing.

    Rounded half-to-even, so the conversion of a floor authored to the hundredth of an
    hour is deterministic and does not drift in one direction across Areas.
    """
    if floor_hours is None:
        return 0
    if floor_hours < 0:
        raise BudgetError(f"a weekly floor of {floor_hours} hours is not a duration")
    return int((floor_hours * MINUTES_PER_HOUR).to_integral_value(rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True, slots=True)
class AreaShare:
    """What one Area declares: an absolute weekly floor, plus a share of the remainder.

    ``parent_id`` is here because a child Area's time rolls up into its parent in reports,
    and the roll-up is arithmetic over the declared set rather than a second query.
    """

    area_id: AreaId
    parent_id: AreaId | None
    floor_minutes: int
    budget_percent: Decimal

    def __post_init__(self) -> None:
        if self.floor_minutes < 0:
            raise BudgetError(f"a floor of {self.floor_minutes} minutes is not a duration")
        if self.budget_percent < 0:
            raise BudgetError(f"a share of {self.budget_percent}% is not a share")
        if self.parent_id == self.area_id:
            raise BudgetError(f"Area {self.area_id} is declared as its own parent")


@dataclass(frozen=True, slots=True)
class AreaAllocation:
    """One Area's row of the budget report.

    ``target`` and ``actual`` are the Area's own. The rolled-up pair adds every descendant,
    because a child's time counts toward its parent in reports while only the leaf declares
    a budget.
    """

    area_id: AreaId
    target_minutes: int
    actual_minutes: int
    rolled_up_target_minutes: int
    rolled_up_actual_minutes: int


@dataclass(frozen=True, slots=True)
class BudgetReport:
    """Every budget figure for one period, each a separately named quantity.

    The denominator is ``discretionary_minutes``, never scheduled time: measuring against
    scheduled time would inflate every Area's share by excluding exactly the hours the user
    never planned.
    """

    discretionary_minutes: int
    allocations: tuple[AreaAllocation, ...]
    unallocated_minutes: int
    oversubscription_minutes: int


def target_minutes(share: AreaShare, *, after_floors: int) -> int:
    """One Area's target: its floor, plus its share of what the floors leave."""
    proportional = (share.budget_percent / _WHOLE_SHARE) * Decimal(after_floors)
    return share.floor_minutes + int(proportional.to_integral_value(rounding=ROUND_DOWN))


def minutes_after_floors(discretionary_minutes: int, shares: Iterable[AreaShare]) -> int:
    """The discretionary minutes the declared floors leave to divide proportionally."""
    floors = sum(share.floor_minutes for share in shares)
    return max(0, discretionary_minutes - floors)


def oversubscription_minutes(allocations: Iterable[AreaAllocation], discretionary: int) -> int:
    """How far the Areas' own targets exceed discretionary time. Zero when they fit."""
    return max(0, sum(allocation.target_minutes for allocation in allocations) - discretionary)


def budget_report(
    *,
    discretionary: IntervalSet,
    shares: Sequence[AreaShare],
    covered: Mapping[AreaId, IntervalSet],
) -> BudgetReport:
    """Every budget figure for the period ``discretionary`` describes.

    ``covered`` maps an Area to the intervals its blocks occupy. Each is intersected with
    the discretionary set before it is measured, so an Area's actual can never count time
    that left the denominator and the wedges plus ``unallocated`` always add up to it.
    """
    discretionary_minutes = discretionary.total_minutes()
    after_floors = minutes_after_floors(discretionary_minutes, shares)
    own_targets = {
        share.area_id: target_minutes(share, after_floors=after_floors) for share in shares
    }
    own_actuals = {
        share.area_id: _claimed_by(share.area_id, covered, within=discretionary) for share in shares
    }
    children = _children_of(shares)
    allocations = tuple(
        AreaAllocation(
            area_id=share.area_id,
            target_minutes=own_targets[share.area_id],
            actual_minutes=own_actuals[share.area_id],
            rolled_up_target_minutes=_rolled_up(share.area_id, children, own_targets),
            rolled_up_actual_minutes=_rolled_up(share.area_id, children, own_actuals),
        )
        for share in shares
    )
    claimed = IntervalSet()
    for share in shares:
        claimed = claimed.union(covered.get(share.area_id, IntervalSet()))
    return BudgetReport(
        discretionary_minutes=discretionary_minutes,
        allocations=allocations,
        unallocated_minutes=discretionary.subtract(claimed).total_minutes(),
        oversubscription_minutes=oversubscription_minutes(allocations, discretionary_minutes),
    )


def _claimed_by(
    area_id: AreaId, covered: Mapping[AreaId, IntervalSet], *, within: IntervalSet
) -> int:
    """The discretionary minutes this Area's blocks occupy."""
    return within.intersect(covered.get(area_id, IntervalSet())).total_minutes()


def _children_of(shares: Sequence[AreaShare]) -> Mapping[AreaId, tuple[AreaId, ...]]:
    """Each Area mapped to its immediate children, in declared order."""
    children: dict[AreaId, list[AreaId]] = {}
    for share in shares:
        if share.parent_id is not None:
            children.setdefault(share.parent_id, []).append(share.area_id)
    return {parent: tuple(found) for parent, found in children.items()}


def _rolled_up(
    area_id: AreaId,
    children: Mapping[AreaId, tuple[AreaId, ...]],
    own: Mapping[AreaId, int],
) -> int:
    """``area_id``'s own figure plus every descendant's.

    Walked with a seen set rather than recursively. The hierarchy is built by declaring a
    child under a parent that already exists, so a cycle cannot form through the API, but
    this function is public and a cycle in its input would otherwise not terminate.
    """
    seen: set[AreaId] = set()
    pending = [area_id]
    total = 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        total += own.get(current, 0)
        pending.extend(children.get(current, ()))
    return total
