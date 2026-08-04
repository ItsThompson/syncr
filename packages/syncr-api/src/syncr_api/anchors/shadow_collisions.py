"""Two commitments close together, and which of the blocks they cast survives.

Every span is measured from one commitment's own time, so two commitments close together cast
blocks that cover the same minutes: a long prep lead reaches back over an earlier journey, and
one commitment's journey home leaves while the next one's journey out should be starting. A
person cannot be in both, so one of them gives way.

**Transit gives way last.** A journey's adjacency to its commitment is what makes it a journey to
it, where a prep lead is a preference about how far ahead to prepare. So prep is fitted around
transit rather than the other way round, and within each kind the earlier-cast commitment keeps
what it cast.

**A block gives way by ending earlier, never by starting later.** Truncating the front would
move a journey off the commitment it meets, and dividing one into two pieces would give one
buffer two identities. So the block that gives way ends where the block it collided with begins,
and it is dropped outright when that leaves nothing a surface could draw.

Only blocks are contested. A forbidden window reserves time for nothing, so two of them
overlapping is a union rather than a contest, and the union is taken where the spans are read.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from syncr_domain.identity import Origin
from syncr_domain.intervals import Interval
from syncr_domain.snap import SNAP

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.anchors.shadow_products import ShadowBlock

# Which block survives a collision, lowest first. Every origin a shadow block can carry has an
# entry, because a precedence that had to fall back to a default would decide silently.
PRECEDENCE_BY_ORIGIN: Final[Mapping[Origin, int]] = {Origin.TRANSIT: 0, Origin.PREP: 1}


def without_collisions(
    in_cast_order: Sequence[tuple[ShadowBlock, ...]],
) -> tuple[ShadowBlock, ...]:
    """The blocks that survive, once no two of them cover the same minute.

    ``in_cast_order`` is one commitment's blocks per member, ordered by the commitment that cast
    them. Blocks are then fitted in precedence order: transit before prep, and within each the
    earlier-cast commitment before the later one.
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
    """``block`` truncated clear of ``kept``, or ``None`` when nothing usable is left.

    The truncated length is measured BEFORE any interval is built, because an interval needs
    ``start < end`` by construction: two blocks beginning at the same instant would otherwise ask
    for a zero-length span and raise, where the answer is that the one giving way is not cast at
    all. The same comparison drops what is left of a block truncated below one grid step, which
    is the shortest span a surface can draw.

    Truncating against the EARLIEST start among the blocks it collided with is what makes one
    pass enough: anything the result could still overlap starts earlier than that, and would have
    supplied that earlier start itself.
    """
    collided = [
        member.interval.start for member in kept if member.interval.overlaps(block.interval)
    ]
    if not collided:
        return block
    truncated_end = min(collided)
    if truncated_end - block.interval.start < SNAP:
        return None
    return replace(block, interval=Interval(block.interval.start, truncated_end))
