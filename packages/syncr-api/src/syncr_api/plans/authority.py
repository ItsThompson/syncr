"""The authority rule, computed: syncr may add, but may never move or remove without permission.

The solver is a global optimizer that answers with a whole week, so something has to decide which
parts of that answer the product may adopt on its own. This module is that decision, and it is a
pure function of two documents: blocks pair on the derived ``BlockId``, so "the same content" is
decidable with no lookup of any kind, which is what makes the rule testable from two literals.

```
classify(live, candidate)
  │
  ├── a candidate block the live plan does not hold:
  │     lands entirely in space no live block covered?
  │       yes ──▶ auto_applicable        a fill
  │       no  ──▶ proposal_diff.added    it displaces something
  ├── a live block the candidate drops   ──▶ proposal_diff.removed
  ├── one block at two placements        ──▶ proposal_diff.moved
  └── a commitment or its buffers over a live block ──▶ conflicts
```

## Auto-application is all or nothing, and that is what bounds the revision count

A fill applies immediately; a move waits. A candidate holding both is **held whole**, because the
alternative is a live plan nobody's solver produced: applying the fills alone would append a
revision composed here, and the proposal held beside it would then describe a live plan that had
just been replaced. So the live plan advances only when the candidate asks for nothing else.

That is also what makes a weekly session cheap. The user pins, every diff therefore contains
moves, so nothing auto-applies, so no revision is appended and no projection is enqueued: twelve
destructive calendar reconciliations during one session would be both slow and visible on the
user's phone, and this falls out of the rule rather than needing a session-specific case.

## The past is not classified at all

A block the week has already reached appears in no output class, whatever authority would say
about it. The reference instant is an argument rather than something read here, for the reason the
solver's own past-block rule takes one: without it the rule has nothing to be decided against, and
a classification computed from a clock would not be reproducible from its inputs.

Filtering here is also what keeps this module out of the question of what authority means over a
block that has started and is pinned. It means nothing, because such a block is not classified.

## Ordering is the classification's own, not the solver's

Every output is ordered by placement and then by identity, so one candidate produces one
classification however the documents were assembled. The stored diff is therefore a value two
readers can compare, and a re-solve of unchanged inputs cannot appear to have changed something by
emitting its blocks in a different order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syncr_api.anchors.shadow_products import DERIVED_ORIGINS
from syncr_api.plans.errors import ClassificationRejected
from syncr_api.plans.overlaps import detected_conflicts
from syncr_domain.identity import Origin
from syncr_domain.intervals import IntervalSet
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_solver.inputs import Anchor, ShadowBlock

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syncr_api.plans.overlaps import DetectedConflict
    from syncr_domain.identity import BlockId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.plan import Block, PlanDocument


@dataclass(frozen=True, slots=True, kw_only=True)
class Classification:
    """What a candidate plan may do on its own, what it must ask about, and what it collides with.

    The three classes are disjoint and each is ordered. ``auto_applicable`` holds fills only: a
    change that displaces something is in the proposal diff instead, which is what the guard below
    states rather than leaves to the producer.
    """

    auto_applicable: tuple[BlockChange, ...] = ()
    proposal_diff: ProposalDiff = field(default_factory=ProposalDiff)
    conflicts: tuple[DetectedConflict, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "auto_applicable", tuple(self.auto_applicable))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
        for change in self.auto_applicable:
            _require_a_fill(change)

    def is_empty(self) -> bool:
        """Whether this candidate changes nothing and collides with nothing.

        A solve that answers with the plan the week already holds leaves no trace beyond its own
        operation record: nothing is appended, nothing is replaced, and nothing is raised.
        """
        return not (self.auto_applicable or self.conflicts) and self.proposal_diff.is_empty()

    def applies_immediately(self) -> bool:
        """Whether the live plan advances without anybody being asked.

        True only for a candidate that fills empty space and does nothing else. A candidate that
        also moves or drops a block is held whole, so this is false and the fills wait with it.
        """
        return bool(self.auto_applicable) and self.proposal_diff.is_empty()


def classify(live: PlanDocument | None, candidate: PlanDocument, *, now: Instant) -> Classification:
    """Partition the difference between the live plan and ``candidate`` into the three classes.

    ``live`` is ``None`` for a week that holds no plan yet, and everything the candidate places in
    such a week fills empty space: there is nothing to displace, nothing to drop, and nothing to
    collide with.

    Raises :class:`~syncr_api.plans.errors.ClassificationRejected` when the two documents describe
    different weeks. Pairing them would compare ids derived against different weeks, so every block
    would read as dropped and every one as added, and the whole week would be proposed as new.
    """
    _require_one_week(live, candidate)
    held = {} if live is None else live.blocks_by_id()
    wanted = candidate.blocks_by_id()
    occupied = IntervalSet(block.interval for block in (() if live is None else live.blocks))
    fills, displacing = _new_blocks(candidate.blocks, held=held, occupied=occupied, now=now)
    return Classification(
        auto_applicable=fills,
        proposal_diff=ProposalDiff(
            added=displacing,
            removed=_dropped(held, candidate=wanted, now=now),
            moved=_relocated(held, candidate=wanted, now=now),
        ),
        conflicts=detected_conflicts(
            live,
            anchors=_commitments(candidate.blocks),
            derived=_buffers(candidate.blocks),
            now=now,
        ),
    )


def _new_blocks(
    blocks: Sequence[Block],
    *,
    held: Mapping[BlockId, Block],
    occupied: IntervalSet,
    now: Instant,
) -> tuple[tuple[BlockChange, ...], tuple[BlockChange, ...]]:
    """The candidate's own new blocks, split by whether they displace anything.

    Space is empty when no live block covers it. A forbidden window and an empty slot are not
    blocks: each exists to explain that nothing is there, so filling one displaces nothing and a
    slot binding late to content is the ordinary auto-application.
    """
    arriving = [
        block for block in blocks if block.id not in held and not _has_started(block.interval, now)
    ]
    return (
        _changes(
            BlockChange.added(block) for block in arriving if not occupied.overlaps(block.interval)
        ),
        _changes(
            BlockChange.added(block) for block in arriving if occupied.overlaps(block.interval)
        ),
    )


def _dropped(
    held: Mapping[BlockId, Block], *, candidate: Mapping[BlockId, Block], now: Instant
) -> tuple[BlockChange, ...]:
    """The live blocks the candidate does not hold. A drop always needs assent."""
    return _changes(
        BlockChange.removed(block)
        for block_id, block in held.items()
        if block_id not in candidate and not _has_started(block.interval, now)
    )


def _relocated(
    held: Mapping[BlockId, Block], *, candidate: Mapping[BlockId, Block], now: Instant
) -> tuple[BlockChange, ...]:
    """The blocks both documents hold at different placements. A move always needs assent.

    A pair is skipped when either placement has started, so a candidate that would move a block
    into the past is refused the same way one that would move it out of the past is: neither is a
    change to a week the product may still revise.
    """
    return _changes(
        BlockChange.moved(live=block, candidate=wanted)
        for block_id, block in held.items()
        if (wanted := candidate.get(block_id)) is not None
        and wanted.interval != block.interval
        and not _has_started(block.interval, now)
        and not _has_started(wanted.interval, now)
    )


def _commitments(blocks: Sequence[Block]) -> tuple[Anchor, ...]:
    """The candidate's imported commitments, as the occupancy shape the detector reads."""
    return tuple(
        Anchor(anchor_id=block.binding.entity_id, interval=block.interval, title=block.title)
        for block in blocks
        if block.origin is Origin.ANCHOR
    )


def _buffers(blocks: Sequence[Block]) -> tuple[ShadowBlock, ...]:
    """The candidate's prep and transit blocks, as the shape the detector reads.

    Each carries an Area by construction, which is what makes it a block rather than a window, so
    the projection loses nothing the detector needs to attribute one to its commitment.
    """
    return tuple(
        ShadowBlock(
            binding=block.binding,
            interval=block.interval,
            area_id=area_id,
            title=block.title,
        )
        for block in blocks
        if block.origin in DERIVED_ORIGINS and (area_id := block.area_id) is not None
    )


def _changes(changes: Iterable[BlockChange]) -> tuple[BlockChange, ...]:
    """One order for every output class: by placement, then by the block's own identity."""
    return tuple(sorted(changes, key=_change_order))


def _change_order(change: BlockChange) -> tuple[Instant, BlockId]:
    placement = change.after or change.before
    # Every change carries at least one placement, which the diff refuses to be built without.
    if placement is None:  # pragma: no cover - unreachable while that guard holds
        raise ClassificationRejected(f"the change to {change.title!r} states no placement at all")
    return (placement.start, change.block_id)


def _has_started(interval: Interval, now: Instant) -> bool:
    """Whether the week has already reached this placement. The past is not classified."""
    return interval.start <= now


def _require_one_week(live: PlanDocument | None, candidate: PlanDocument) -> None:
    if live is None or live.iso_week == candidate.iso_week:
        return
    raise ClassificationRejected(
        f"a classification pairs two documents of one week, and these are {live.iso_week} and "
        f"{candidate.iso_week}: an id is derived against the week, so every block would read as "
        "dropped and every one as added, and the whole week would be proposed as new"
    )


def _require_a_fill(change: BlockChange) -> None:
    """A change that applies without asking displaces nothing, so it replaces no placement.

    The one guard that makes "syncr may add" true of the value rather than of the code that built
    it: a change carrying a placement it replaced would move something on the user's behalf under
    a revision that says only empty space was filled.
    """
    if change.before is None:
        return
    raise ClassificationRejected(
        f"the change to {change.title!r} applies without asking and states a placement it "
        "replaced: a fill lands in space no block covered, so applying one moves nothing"
    )
