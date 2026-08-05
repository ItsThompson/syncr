"""The pie review's arithmetic: what a period observed, and the revision it proposes.

`syncr_domain.budgets` computes what a budget CLAIMS. This computes what behaviour SAYS, and
proposes a share to close the difference. The two are separate modules because they answer
opposite questions and only one of them is a proposal: nothing here writes, and nothing that
reads it may apply a proposal without the user assenting.

## What counts as data

**Only a week whose every planned day is confirmed contributes to a proposal.** A partly
confirmed week has its actuals over some days and its denominator over all seven, so its
observed share is understated by exactly the days nobody answered for. Reporting that figure
as behaviour would propose a smaller share for an Area whose real failing was that the user
stopped confirming, which is the review inventing a budget from an absence.

A partly confirmed week is still REPORTED: `16-frontend-shell.md`'s review states the
confirmed and unconfirmed day counts of its period, so the reader is told how much of the
period the figures rest on. What such a week does not do is move a percentage.

**A quarter is thirteen weeks**, and until thirteen contributing weeks exist there is no
proposal at all. The review then shows the gap between actual and target and says why the
other half is missing. A proposal from three weeks would fit a quarter's budget to one
unusual month.

## The proposal rule

```
proposed = declared + trunc((observed - declared) / 2), bounded to 0 .. 100
```

**Half the distance, not the whole of it.** Setting the target to the observed share makes the
budget a description of the past, and a budget that ratifies whatever happened cannot starve an
Area, which is the one thing it exists to prevent. Half moves the target toward reality while
leaving the gap visible so the next review can move it again.

**The DISTANCE is truncated, not the midpoint**, and that is what gives the rule its two
properties. A truncated distance is never larger than half the real one, so a proposal can never
pass the observed share, and a gap under two points moves nothing at all. Truncating the midpoint
instead breaks both: a share declared at 20 and observed at 19.9 has a midpoint of 19.95, which
truncates to 19 and lands FURTHER from the observation than the declaration was, off a gap of a
tenth of a point.

Toward zero, which is the rounding `budgets.target_minutes` uses, so a proposal never rounds a set
of shares up into an oversubscription the observed behaviour does not describe.

**An Area declaring a floor is left alone.** Its floor is what holds its time: the share only
divides what the floors leave, so proposing a smaller share for an Area whose floor is already
doing the work would change a figure that is not the one being missed.

## The vacancy is a category here

Discretionary time no block covered is a row of the proposal like any Area, because it is the
gap the review exists to surface, and the same rule applies to it. Its `area_id` is ``None``:
there is nothing to write a share to, so applying a revision changes Areas and the vacancy's
share follows from theirs.

## The vacancy's own figure is counts, not sets

`budgets.unallocated_minutes` subtracts one interval set from another, which is what makes it
non-negative by construction. :func:`uncovered_minutes` here does the same subtraction over two
counts, because a review's denominator is the plan of record's stored scalar and the set behind it
is not stored. The difference is stated at that function, with the one case its clamp exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.identifiers import AreaId

# A quarter of confirmed data, in weeks. Thirteen, which is a calendar quarter, and the count
# `02-user-stories.md` US-REV-03 means by "before a quarter of confirmed data exists".
QUARTER_WEEKS: Final = 13

# The whole of a share, as `budget_percent` is authored: 25 means a quarter.
WHOLE_SHARE: Final = Decimal(100)

# An observed share is reported to a tenth of a point, which is what the rendered budget sheet
# states and what a reader can compare down a column. A proposal is a whole point, because a
# share authored to a tenth reads as a precision the arithmetic behind it does not have.
_OBSERVED_PLACES: Final = Decimal("0.1")
_HALF: Final = Decimal(2)


class BudgetReviewError(DomainError):
    """The reviewed period cannot be read as one."""


class ProposalBasis(StrEnum):
    """Why one category's proposal is what it is.

    A closed vocabulary rather than free prose, so a caller may group rows by reason and a
    renderer's sentence for each is one table rather than a formatting decision per row.
    """

    FLOOR_HOLDS_IT = "floor_holds_it"
    NEVER_MET = "never_met"
    SUSTAINED_UNDER = "sustained_under"
    SUSTAINED_OVER = "sustained_over"
    ALREADY_THERE = "already_there"


@dataclass(frozen=True, slots=True)
class ReviewedCategory:
    """What one Area, or the vacancy, declared and what the contributing weeks observed.

    ``area_id`` is ``None`` for the vacancy. ``declared_percent`` is the share in effect now
    rather than the one each past week was solved under: the review exists to decide whether to
    change the current budget, so the current budget is what the comparison is against.
    """

    area_id: AreaId | None
    declared_percent: Decimal
    observed_percent: Decimal
    holds_a_floor: bool
    weeks_short_of_target: int
    weeks_counted: int

    def __post_init__(self) -> None:
        if self.weeks_counted < 0:
            raise BudgetReviewError(f"{self.weeks_counted} weeks is not a count of weeks")
        if not 0 <= self.weeks_short_of_target <= self.weeks_counted:
            raise BudgetReviewError(
                f"{self.weeks_short_of_target} of {self.weeks_counted} weeks were short of "
                "target, which is more weeks than were counted"
            )


@dataclass(frozen=True, slots=True)
class ProposedShare:
    """One row of the proposed revision: what is declared, what happened, and what to declare."""

    area_id: AreaId | None
    declared_percent: Decimal
    observed_percent: Decimal
    proposed_percent: Decimal
    basis: ProposalBasis


def uncovered_minutes(discretionary_minutes: int, claimed_minutes: int) -> int:
    """Discretionary minutes no confirmed block covered, from two counts rather than two sets.

    `budgets.unallocated_minutes` is the canonical form and takes the two interval SETS, which is
    what makes it non-negative by construction. A review cannot: its denominator is the plan of
    record's own stored figure, a scalar, and the set that figure was taken over is not stored
    beside it. Rebuilding that set is what ticket 1310 is for, and rebuilding it from the document
    alone overstates it by the preceding week's frame overhang.

    So the figure is a subtraction of counts, and the clamp is load-bearing rather than defensive.
    It is reachable: a ``moved`` outcome carries a user-supplied interval, and one reported inside
    the circadian frame is time that was never in the denominator. Without the clamp such a week
    reports a negative vacancy, which is not a wedge, and which is the defect an earlier draft's
    ``discretionary - sum(target)`` formula had for a different reason.
    """
    return max(0, discretionary_minutes - claimed_minutes)


def observed_percent(actual_minutes: int, discretionary_minutes: int) -> Decimal:
    """``actual_minutes`` as a share of the discretionary time it was measured against.

    Zero when there was no discretionary time to divide, which is a week declared off-plan from
    end to end: nothing was observed because there was nothing to observe, and a division would
    raise on the honest input.

    Rounded half-to-even to a tenth of a point, so the figure does not drift in one direction
    across a column of Areas.
    """
    if discretionary_minutes <= 0:
        return Decimal(0)
    share = (Decimal(actual_minutes) / Decimal(discretionary_minutes)) * WHOLE_SHARE
    return share.quantize(_OBSERVED_PLACES, rounding=ROUND_HALF_EVEN)


def has_a_quarter_of_confirmed_data(confirmed_weeks: int) -> bool:
    """Whether enough confirmed weeks exist for the proposal half of the review to say anything."""
    return confirmed_weeks >= QUARTER_WEEKS


def proposed_share(category: ReviewedCategory) -> ProposedShare:
    """The share to declare for one category, and why.

    The order of the reasons is the order of their authority. A floor outranks everything,
    because the share is not the figure holding that Area's time. A proposal equal to what is
    already declared says so rather than claiming a direction it does not move in. A target
    missed in every counted week is a stronger statement than a target missed on average, and
    it is the one the rendered review draws.
    """
    proposed = _bounded(_halved(category.declared_percent, category.observed_percent))
    return ProposedShare(
        area_id=category.area_id,
        declared_percent=category.declared_percent,
        observed_percent=category.observed_percent,
        proposed_percent=category.declared_percent if category.holds_a_floor else proposed,
        basis=_basis_of(category, proposed=proposed),
    )


def proposed_shares(categories: Sequence[ReviewedCategory]) -> tuple[ProposedShare, ...]:
    """A proposal per category, in the order given."""
    return tuple(proposed_share(category) for category in categories)


def _basis_of(category: ReviewedCategory, *, proposed: Decimal) -> ProposalBasis:
    if category.holds_a_floor:
        return ProposalBasis.FLOOR_HOLDS_IT
    if proposed == category.declared_percent:
        return ProposalBasis.ALREADY_THERE
    if category.weeks_counted > 0 and category.weeks_short_of_target == category.weeks_counted:
        return ProposalBasis.NEVER_MET
    if category.observed_percent < category.declared_percent:
        return ProposalBasis.SUSTAINED_UNDER
    return ProposalBasis.SUSTAINED_OVER


def _halved(declared: Decimal, observed: Decimal) -> Decimal:
    """The declared share moved by half the distance to the observed one, truncated toward zero.

    The DISTANCE is what truncates. Truncating the sum instead would let a tenth-of-a-point gap
    move a share by a whole point, past the observation it was moving toward.
    """
    return declared + ((observed - declared) / _HALF).to_integral_value(rounding=ROUND_DOWN)


def _bounded(percent: Decimal) -> Decimal:
    """A share inside the range a share can be authored in.

    Reachable from below only: an observed share cannot exceed the whole, so a midpoint above
    100 needs a declared share already past it, which is a legitimate oversubscribed
    declaration.
    """
    return min(max(percent, Decimal(0)), WHOLE_SHARE)
