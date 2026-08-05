"""The shape rules: what length a block may take, and where its bounds may fall.

H6, H7 and H14. Two of them read how much of a demand a candidate places and one reads the grid,
and all three judge the candidate alone: none of them looks at what else the week holds.

H6 and H7 divide the sizing question between them rather than overlapping, and the division is the
``splittable`` flag. An atomic demand is this duration or nothing, so anything short of the whole
is refused and a minimum chunk would name a division it does not have. A divisible demand may be
placed in pieces, and what it owes is that each piece is usable.

H14's exemption is what makes the grid a snap target for the user's own placements rather than a
claim about every block. An imported commitment keeps its real time even at ``:07``, and the
buffers derived from it are computed from that time, so a 30-minute journey before a 16:07
commitment starts at 15:37 and is legal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_domain.identity import BindingKind
from syncr_domain.snap import SNAP_MINUTES, is_on_snap_grid
from syncr_solver.constraints import Blocked, ConstraintRule

if TYPE_CHECKING:
    from syncr_solver.state import PartialPlan, Placement

# The kinds the fifteen-minute grid does not bind: an imported commitment, and the prep and transit
# buffers computed from its real time. A recovery window is exempt for the same reason and is not
# here, because a window is not a block and no candidate carries it.
EXEMPT_FROM_THE_SNAP: Final = frozenset(
    {BindingKind.ANCHOR, BindingKind.ANCHOR_PREP, BindingKind.ANCHOR_TRANSIT}
)


def atomic_not_splittable(candidate: Placement, _: PartialPlan) -> Blocked | None:
    """H6. ``splittable is False`` means this duration or nothing.

    Two ways to divide one: numbering the candidate as a chunk, and placing less of it than is
    left. The first is how a divided task is represented and the second is how a partial placement
    would look without one, so both are refused and either alone would leave the other reachable.
    """
    sizing = candidate.sizing
    if sizing is None or sizing.splittable:
        return None
    if candidate.binding.split_index is not None:
        return Blocked(
            ConstraintRule.ATOMIC_NOT_SPLITTABLE,
            candidate.interval,
            f"{candidate.title} is not splittable, and this is chunk "
            f"{candidate.binding.split_index}",
        )
    if candidate.minutes() < sizing.whole_minutes:
        return Blocked(
            ConstraintRule.ATOMIC_NOT_SPLITTABLE,
            candidate.interval,
            f"{candidate.title} takes {sizing.whole_minutes}m or nothing, "
            f"and this is {candidate.minutes()}m",
        )
    return None


def below_min_chunk(candidate: Placement, _: PartialPlan) -> Blocked | None:
    """H7. A divisible demand is placed in usable pieces, never below the minimum it states.

    Read only for a divisible demand. An atomic one is bounded by H6 at its whole duration, which
    is a stricter bound than its minimum chunk, so reading the minimum here as well would report
    the wrong rule for the same rejection.

    Neither rule bounds a placement from ABOVE, and that symmetry is deliberate: an elastic
    occurrence sized past its smallest legal length and a task placed past what is left of it are
    the same shape, and over-allocating is charged by the objective's budget term rather than
    forbidden here. So a demand whose minimum chunk exceeds what is left of it has nothing this rule
    will accept below the minimum and nothing that refuses one piece at the minimum. That is the
    packing failure the verdict reports, not a rule missing from the table.
    """
    sizing = candidate.sizing
    if sizing is None or not sizing.splittable:
        return None
    if candidate.minutes() < sizing.min_chunk_minutes:
        return Blocked(
            ConstraintRule.BELOW_MIN_CHUNK,
            candidate.interval,
            f"{candidate.title} is placed in {sizing.min_chunk_minutes}m at least, "
            f"and this is {candidate.minutes()}m",
        )
    return None


def snap(candidate: Placement, _: PartialPlan) -> Blocked | None:
    """H14. Every start and end lands on the quarter hour, except an imported fact's.

    Both bounds are read rather than only the start, because a duration off the grid moves an end
    off it from a start that was on it.
    """
    if candidate.binding.kind in EXEMPT_FROM_THE_SNAP:
        return None
    off = [
        str(moment)
        for moment in (candidate.interval.start, candidate.interval.end)
        if not is_on_snap_grid(moment)
    ]
    if not off:
        return None
    return Blocked(
        ConstraintRule.SNAP,
        candidate.interval,
        f"{candidate.title} is off the {SNAP_MINUTES}-minute grid at {', '.join(off)}",
    )
