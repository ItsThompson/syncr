"""Two commitments close together, and which of the blocks they cast survives.

Every span is measured from one commitment's own time, so two commitments close together cast
blocks that cover the same minutes: a long prep lead reaches back over an earlier journey, and
one commitment's journey home leaves while the next one's journey out should be starting. A
person cannot be in both, so one of them gives way.

**Transit gives way last.** A journey's adjacency to its commitment is what makes it a journey to
it, where a prep lead is a preference about how far ahead to prepare. So prep is fitted around
transit rather than the other way round, and within each kind the earlier-cast commitment keeps
what it cast. One consequence carries the rest of this rule: every leg is fitted before every prep,
so the only thing a leg ever gives way to is another leg.

**No block moves its start, and no block is divided.** A start is the one instant a declaration
actually names: prep starts at its lead, a leg starts at its lead, and a return leg starts at the
commitment's end. Moving a start forward would put a buffer at a time nothing declared, and
dividing a block into the pieces either side of an obstacle would give one buffer two identities,
since identity is derived from the binding. What is left to choose is therefore per kind, and the
two kinds answer differently.

**A prep block that gives way ends where the block it collided with begins**, and it is dropped
outright when that leaves nothing a surface could draw. A shortened prep is still prep: the lead is
a preference about how far ahead to prepare, so less time to prepare is a smaller version of the
same thing.

**A leg that gives way is dropped whole.** A journey is a journey because of where it arrives, and
a truncated leg arrives nowhere: the outbound leg's end is its meeting with the commitment, and the
journey home's end is home. Cutting an abutting 09:00-11:00 leg at 10:00 leaves the hour before the
commitment uncovered and tells the user to travel at a time they do not, which is the adjacency the
prep-versus-transit ordering exists to protect.

**What dropping costs, stated rather than implied: nothing is reserved for a journey the user
declared, so that travel is unbudgeted.** The commitment itself is still hard occupancy, so nothing
is scheduled over the anchor. And an absence explains nothing on its own: a reader cannot tell a
dropped leg from a leg no type ever declared, so whatever draws the day has to say which it is.

Only blocks are contested. A forbidden window holds no content and reserves time for nothing to be
placed in, so two of them covering the same minutes is a union rather than a contest, and the union
is taken where the spans are read.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from syncr_domain.identity import Origin
from syncr_domain.intervals import Interval
from syncr_domain.snap import SNAP

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from syncr_api.anchors.shadow_products import ShadowBlock
    from syncr_domain.intervals import Instant

# Which block survives a collision, lowest first. Every origin a shadow block can carry has an
# entry, because a precedence that had to fall back to a default would decide silently.
PRECEDENCE_BY_ORIGIN: Final[Mapping[Origin, int]] = {Origin.TRANSIT: 0, Origin.PREP: 1}

# What one kind of block does when it loses a collision, given the earliest start it lost to.
type GiveWay = Callable[[ShadowBlock, Instant], ShadowBlock | None]


def without_collisions(
    in_cast_order: Sequence[tuple[ShadowBlock, ...]],
) -> tuple[ShadowBlock, ...]:
    """The blocks that survive, once no two of them cover the same minute.

    ``in_cast_order`` is one commitment's blocks per member, ordered by the commitment that cast
    them. Blocks are then fitted in precedence order: transit before prep, and within each the
    earlier-cast commitment before the later one.

    Returned in that same **precedence** order, which is not the order they run in: the set that
    holds them normalizes to interval order, so no caller depends on this one.
    """
    kept: list[ShadowBlock] = []
    candidates = [(cast, block) for cast, blocks in enumerate(in_cast_order) for block in blocks]
    for _, block in sorted(candidates, key=_precedence):
        fitted = _fitted(block, kept)
        if fitted is not None:
            kept.append(fitted)
    return tuple(kept)


def _precedence(candidate: tuple[int, ShadowBlock]) -> tuple[int, int, Interval]:
    """Transit before prep, earlier-cast before later-cast, and earlier before later within one.

    Total, so the answer is the same however the blocks arrive: one commitment casts at most one
    prep and two journeys, and the two journeys are separated by the span each covers.
    """
    cast, block = candidate
    return (PRECEDENCE_BY_ORIGIN[block.origin], cast, block.interval)


def _fitted(block: ShadowBlock, kept: Sequence[ShadowBlock]) -> ShadowBlock | None:
    """``block`` as it survives ``kept``, or ``None`` when it does not survive at all.

    How it gives way is read from its origin rather than from the collision, so a leg and a prep
    covering the same minutes of the same obstacle still answer differently.

    Measuring against the EARLIEST start among the blocks it collided with is what makes one pass
    enough: anything the result could still overlap starts earlier than that, and would have
    supplied that earlier start itself.
    """
    collided = [
        member.interval.start for member in kept if member.interval.overlaps(block.interval)
    ]
    if not collided:
        return block
    return GIVES_WAY_BY_ORIGIN[block.origin](block, min(collided))


def _dropped(block: ShadowBlock, earliest_collision: Instant) -> None:
    """Nothing, because a leg that cannot reach what it is a journey to is not a shorter journey.

    Takes the collision it lost to, like the truncation beside it, so the two shapes a block can
    give way in are stated in one vocabulary and neither reads as the special case.
    """
    return


def _truncated(block: ShadowBlock, earliest_collision: Instant) -> ShadowBlock | None:
    """``block`` ending where ``earliest_collision`` begins, or ``None`` when too little is left.

    The truncated length is measured BEFORE any interval is built, because an interval needs
    ``start < end`` by construction: two blocks beginning at the same instant would otherwise ask
    for a zero-length span and raise, where the answer is that the one giving way is not cast at
    all. The same comparison drops what is left of a block truncated below one grid step, which
    is the shortest span a surface can draw.
    """
    if earliest_collision - block.interval.start < SNAP:
        return None
    return replace(block, interval=Interval(block.interval.start, earliest_collision))


# How a block that gives way does so, per kind. Every origin a shadow block can carry has an entry,
# for the same reason the precedence table does: a kind that had to fall back to a default would
# give way silently.
GIVES_WAY_BY_ORIGIN: Final[Mapping[Origin, GiveWay]] = {
    Origin.TRANSIT: _dropped,
    Origin.PREP: _truncated,
}
