"""The three minute figures a plan document carries, over one week's inputs and its blocks.

Every figure beside the document is derived from the document, so these are computed once, here,
from the same arithmetic the budget report uses. A wrong answer is a plausible-looking report
rather than a crash, which is the failure this product cannot detect any other way.

## What each figure counts

``discretionary_minutes`` is the denominator: the week's span less the four spans no Area can
claim, unioned before subtraction because three of them routinely overlap.

``unallocated_minutes`` is discretionary time no block carrying an Area covers. An unfilled slot
increases it, and so does a recovery window scoped to named Areas: both are time some Area could
have claimed and none did. It is a subtraction of sets rather than a residual against Area
targets, so it is non-negative and no larger than the denominator by construction.

``oversubscription_minutes`` is how far the Areas' own targets exceed that denominator, and zero
when they fit. The targets arrive already computed for this week, so this reads them rather than
re-deriving a share.

## Why the denominator is taken over the inputs rather than over the emitted blocks

The four subtrahends are facts about the week: the frame, the commitments, the windows that
forbid every Area, and the spans declared off. A document's blocks are what was placed inside
what is left, so measuring the denominator over them would make the figure depend on how much of
the week got placed, and a week's denominator does not move when a placement is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.budgets import oversubscription_minutes, unallocated_minutes
from syncr_domain.discretionary import absolute_forbidden, discretionary_intervals
from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.plan import Block
    from syncr_solver.inputs import SolveInputs


@dataclass(frozen=True, slots=True)
class WeekFigures:
    """The three minute figures, computed together so none can disagree with the others."""

    discretionary_minutes: int
    unallocated_minutes: int
    oversubscription_minutes: int


def week_figures(inputs: SolveInputs, blocks: Sequence[Block]) -> WeekFigures:
    """Every figure one week's document carries, over its inputs and the blocks placed in it."""
    discretionary = discretionary_intervals(
        inputs.span,
        frame=inputs.frame_occupancy(),
        anchors=IntervalSet(anchor.interval for anchor in inputs.anchors),
        absolute_forbidden=absolute_forbidden(inputs.forbidden_windows),
        off_plan=IntervalSet(period.interval for period in inputs.off_plan),
    )
    return WeekFigures(
        discretionary_minutes=discretionary.total_minutes(),
        unallocated_minutes=unallocated_minutes(discretionary, claimed_intervals(blocks)),
        oversubscription_minutes=oversubscription_minutes(
            (area.target_minutes for area in inputs.areas), discretionary.total_minutes()
        ),
    )


def claimed_intervals(blocks: Sequence[Block]) -> IntervalSet:
    """The spans some Area's blocks cover, unioned, so a minute claimed twice is claimed once.

    An Area is what makes a block a claim on discretionary time: the frame and an anchor carry
    none, because one defines how much time exists and the other is time the product does not
    own, and both are already out of the denominator.

    Public because the objective's fragmentation term reads the same set from the other side: the
    gaps a plan leaves are the discretionary time this does NOT cover, and a second statement of
    what an Area claims would let the figure a document reports and the gaps a term charges
    disagree about one block.
    """
    return IntervalSet(block.interval for block in blocks if block.area_id is not None)
