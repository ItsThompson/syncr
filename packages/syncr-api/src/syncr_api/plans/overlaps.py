"""The overlaps nothing may resolve silently, detected against the live plan.

syncr's own solver output is overlap-free, so a visible overlap is always one of exactly three
things. Two of them are settled without asking anybody: a user-authored multitask is left alone,
and a derived buffer displacing an unpinned block runs through the authority rule as a change
that waits for assent. The third has nobody to ask and nothing to move, and that is what this
module finds.

| The overlap | Why it cannot be settled quietly |
|---|---|
| an imported commitment over a planned, non-anchor block | the commitment is a fact the product
  does not own, and the block is the user's own week |
| a derived prep or transit block over a **pinned** block | both are immovable: one is fixed by
  the anchor's geometry and the other is the user's own edit |

The second is attributed to the **anchor**, not to the buffer, because the anchor is the fact
that arrived and the buffer is only its consequence. Nothing else in the model catches it: the
solver created neither block, so the no-overlap rule is satisfied, and both are immovable, so a
re-solve changes nothing. Without this it would sit in the week with nothing raised.

## What is deliberately not detected

**A commitment over another commitment.** Two genuine commitments can genuinely overlap, and the
product does not own either of them.

**A commitment over the buffers it cast itself.** Prep and the outbound leg both end at or before
the commitment starts, and the return leg begins exactly where it ends, so a commitment provably
never overlaps its own products. The rule is enforced where a type is declared, by a validation
and by a check constraint, so no exemption is needed here.

**A buffer over the block that IS that buffer, moved.** The user may pin a derived block
elsewhere, which is how a longer-than-usual commute is expressed. The fresh geometry then covers
the buffer's original span while the pin holds the same content somewhere else, and that is one
block at two placements rather than two blocks colliding, so the pair is exempt by its shared
identity.

**Anything over a block that has started.** A resolution moves the block, removes the pin holding
it, or accepts the overlap, and the first two are refused on a block the week has already reached.
Raising a notice no resolution can act on is what teaches a user to mute the one notification this
product sends.

**An off-plan span suppresses nothing here.** A commitment during a period the user declared off
is still a commitment: off-plan suspends syncr's scheduling, not the world's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.identity import Origin

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_domain.identifiers import AnchorId
    from syncr_domain.identity import BlockId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import Anchor, ShadowBlock


@dataclass(frozen=True, slots=True, kw_only=True)
class DetectedConflict:
    """One overlap that needs an answer: which commitment, which block, and where they meet.

    The pure half of a stored conflict. It carries no identifier and no instant of detection,
    because a value computed from two documents mints neither: the repository that raises the row
    supplies both.
    """

    anchor_id: AnchorId
    block_id: BlockId
    overlap: Interval


def detected_conflicts(
    live: PlanDocument | None,
    *,
    anchors: Sequence[Anchor] = (),
    derived: Sequence[ShadowBlock] = (),
    now: Instant,
) -> tuple[DetectedConflict, ...]:
    """Every overlap between ``live`` and what these commitments put in the week.

    ``anchors`` are the commitments themselves and ``derived`` are the prep and transit blocks
    their types cast. Both are the resolved shapes an assembly already holds, so a caller supplies
    what it read rather than building a shape for this call: at ingest they are the week's
    commitments and their fresh geometry, and on the commit path they are the candidate plan's own
    anchor and buffer blocks.

    A week with no live plan holds nothing to collide with, which is why ``live`` is nullable
    rather than faked as an empty document: a week the horizon has not reached has no figures to
    invent.

    **One conflict per commitment and block**, carrying the earliest span the two share. A
    commitment can reach one block both itself and through a buffer it cast, and the notice names
    a commitment and a block, so a second row for one pair would ask the same question twice.
    """
    if live is None:
        return ()
    found: dict[tuple[AnchorId, BlockId], DetectedConflict] = {}
    for conflict in sorted(_overlaps(live, anchors=anchors, derived=derived, now=now), key=_order):
        found.setdefault((conflict.anchor_id, conflict.block_id), conflict)
    return tuple(found.values())


def _overlaps(
    live: PlanDocument,
    *,
    anchors: Sequence[Anchor],
    derived: Sequence[ShadowBlock],
    now: Instant,
) -> Iterator[DetectedConflict]:
    """Both classes of overlap, over the blocks the week may still be asked about."""
    revisable = tuple(block for block in live.blocks if now < block.interval.start)
    for anchor in anchors:
        for block in revisable:
            if block.origin is Origin.ANCHOR:
                continue
            found = _conflict(anchor.anchor_id, block, anchor.interval)
            if found is not None:
                yield found
    for buffer in derived:
        for block in revisable:
            if not block.pinned or block.binding == buffer.binding:
                continue
            found = _conflict(buffer.binding.entity_id, block, buffer.interval)
            if found is not None:
                yield found


def _conflict(anchor_id: AnchorId, block: Block, arriving: Interval) -> DetectedConflict | None:
    """The conflict this pair raises, or ``None`` when they do not meet.

    The shared span is taken by clipping rather than compared first, because the algebra refuses a
    zero-length interval by construction: two spans that abut share no minute, and the clip
    answering ``None`` is that same statement.
    """
    overlap = arriving.clipped_to(block.interval)
    if overlap is None:
        return None
    return DetectedConflict(anchor_id=anchor_id, block_id=block.id, overlap=overlap)


def _order(conflict: DetectedConflict) -> tuple[Interval, BlockId, str]:
    """Earliest overlap first, so one week's conflicts are raised in the order they occur.

    Total, so a detection is a value: two commitments meeting one block at the same instant are
    separated by the identifiers, and nothing downstream depends on the order the caller read
    either collection in.
    """
    return (conflict.overlap, conflict.block_id, str(conflict.anchor_id))
