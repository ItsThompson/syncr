"""What a week's commitments occupy: the anchors themselves, and what their types cast.

The generator in :mod:`syncr_api.anchors.shadows` produces unclipped spans from one commitment's
own time, because which of them fall inside a week is a question only the caller holding that
week's span can answer. This module is that caller's answer, and it holds the three decisions
that answer needs.

## Clipped, or carried whole, and the reason differs

**A shadow is clipped to the week and dropped when nothing is left.** A prep block is syncr's own
derived content, and which week holds it is decided by where it falls: the evening before a
Monday-morning exam belongs to the week that evening is in.

**An anchor is carried whole.** Its duration is the publisher's fact rather than this week's
reading of it, and every figure taken over it subtracts inside the span anyway, so clipping would
buy nothing and would leave a truncated commitment for whatever draws one. Only the anchors that
overlap the week are carried: one loaded solely so its shadow could be generated occupies no time
here.

**A frame occurrence crossing the boundary is neither.** One week owns it whole and the next reads
its overhang, which is :mod:`syncr_api.plans.overhang`'s question rather than this module's.

## An off-plan span suppresses a block and not a window

Prep and transit blocks are content: they carry an Area and consume its budget in the same way a
task does, so a declared off-plan span suppresses them along with every other discretionary
thing, by the same overlap rule that suppresses a template entry. A recovery window is not
suppressed, and nothing turns on that either way: it forbids work in a span where no work is
being scheduled at all. It is kept because a window explains a gap, and the gap is real.

An anchor is not suppressed by anything. A commitment during a period the user declared off is
still a commitment: off-plan suspends syncr's scheduling, not the world's.

## An anchor whose type this read did not see is opaque busy time

Two statements read a snapshot each under Postgres' default isolation, so a type created between
them can be carried by an anchor that arrives without it. The anchor is then treated as untyped:
it occupies its own time and casts nothing, and the event is logged. The alternative is what the
generator does when a pair disagrees, which is to refuse, and refusing here would fail every
solve, pin, and live verdict for the week over a race that a version bump already re-solves.

The mirror race needs no degradation: releasing a type from its anchors and deleting it are one
transaction, so a delete that commits between the two reads is answered by anchors that no longer
carry it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.anchors.shadow_products import ShadowSet
from syncr_api.anchors.shadows import TypedAnchor, regenerate
from syncr_common.logging import get_logger
from syncr_domain.gaps import EmptySlot, EmptySlotReason, ForbiddenWindow
from syncr_domain.intervals import IntervalSet
from syncr_solver.inputs import Anchor, ShadowBlock

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.anchors.records import AnchorRecord, AnchorTypeId, AnchorTypeRecord
    from syncr_api.anchors.shadow_products import ShadowBlock as CastBlock
    from syncr_api.plans.materialization import OffPlanSuppression
    from syncr_domain.intervals import Interval

_log = get_logger("syncr.plans")


@dataclass(frozen=True, slots=True)
class CalendarOccupancy:
    """One week's calendar half: hard occupancy, derived blocks, and the windows.

    The three fields the solve inputs carry, plus the two sets the discretionary denominator
    subtracts, so a caller composing that denominator asks this rather than deciding for itself
    which window kinds leave it.
    """

    anchors: tuple[Anchor, ...] = ()
    shadow_blocks: tuple[ShadowBlock, ...] = ()
    forbidden_windows: tuple[ForbiddenWindow, ...] = ()
    # The journeys a collision dropped whole inside the span, as the empty slots that explain
    # them. An absence explains nothing on its own, so the cause travels in the same reason
    # vocabulary every other explained gap uses rather than as a blank the reader guesses at.
    dropped_legs: tuple[EmptySlot, ...] = ()

    def anchor_spans(self) -> IntervalSet:
        """The time the commitments themselves occupy, unioned.

        Unioned rather than summed because two calendars can each publish one meeting and two
        genuine commitments can genuinely overlap, and summing those durations would subtract the
        shared minutes twice.
        """
        return IntervalSet(anchor.interval for anchor in self.anchors)

    def absolute_forbidden(self) -> IntervalSet:
        """The spans no Area may claim, unioned.

        Read through the shadow set's own reading of the subtraction table rather than by
        filtering a scope here, so which window kinds leave the denominator has one statement.
        """
        return ShadowSet(forbidden=self.forbidden_windows).absolute_forbidden()


def typed_anchors(
    anchors: Sequence[AnchorRecord], types: Sequence[AnchorTypeRecord]
) -> tuple[TypedAnchor, ...]:
    """Each anchor paired with the type it carries, in the order the anchors were read.

    An anchor carrying a type this read did not see is paired with none through
    :meth:`TypedAnchor.untyped`, and the count is reported: the pair the generator is given has to
    agree, and a type created between two statements of one transaction is a race rather than a
    state worth failing an assembly for.
    """
    by_id: Mapping[AnchorTypeId, AnchorTypeRecord] = {row.id: row for row in types}
    paired: list[TypedAnchor] = []
    unread = 0
    for anchor in anchors:
        carried = anchor.anchor_type_id
        found = None if carried is None else by_id.get(carried)
        if carried is not None and found is None:
            unread += 1
            paired.append(TypedAnchor.untyped(anchor))
            continue
        paired.append(TypedAnchor(anchor, found))
    if unread:
        _log.warning(
            "plans.assembly.anchor_type_unread",
            anchors_with_an_unread_type=unread,
            anchors_read=len(anchors),
            types_read=len(by_id),
        )
    return tuple(paired)


def calendar_occupancy(
    loaded: Sequence[TypedAnchor], *, span: Interval, off_plan: OffPlanSuppression
) -> CalendarOccupancy:
    """Everything ``loaded`` occupies inside ``span``, and everything its types cast there.

    ``loaded`` covers a wider span than ``span``, because a commitment outside the week can cast a
    product inside it. Collisions are resolved over the whole loaded set rather than over the
    week's own members, so a commitment the week does not contain still takes precedence over one
    it does.

    **What that does not buy is an answer independent of the week's edge.** The loaded set holds
    every commitment that can cast INSIDE the week, which is not every commitment that can cast
    over one of those products: a journey home ending before the read begins truncates a prep block
    in the week that reads both and not in the week that reads only the prep. The consequence is two
    derived blocks covering the same minutes, which is a state the grid draws, and it is measured in
    the suite rather than argued.
    """
    cast = regenerate(loaded)
    return CalendarOccupancy(
        anchors=tuple(
            Anchor(anchor_id=pair.anchor.id, interval=pair.anchor.interval, title=pair.anchor.title)
            for pair in loaded
            if pair.anchor.interval.overlaps(span)
        ),
        shadow_blocks=tuple(
            _as_solve_input(cast_block, inside)
            for cast_block in cast.blocks
            if (inside := cast_block.interval.clipped_to(span)) is not None
            and not off_plan.suppresses_content(inside)
        ),
        forbidden_windows=tuple(
            replace(window, interval=inside)
            for window in cast.forbidden
            if (inside := window.interval.clipped_to(span)) is not None
        ),
        dropped_legs=tuple(
            _as_explained_gap(dropped, inside)
            for dropped in cast.dropped_legs
            if (inside := dropped.interval.clipped_to(span)) is not None
            and not off_plan.suppresses_content(inside)
        ),
    )


def _as_explained_gap(leg: CastBlock, interval: Interval) -> EmptySlot:
    """One dropped journey, at the span this week holds of it, as an explained gap.

    The reason is a member of the one vocabulary every empty surface reads, so the grid states
    the cause instead of drawing nothing where a declared journey would have been. Charged to
    the leg's own Area, which every contested leg has: a buffer whose type named no Area became
    a forbidden window at generation and was never a block a collision could drop.
    """
    return EmptySlot(interval=interval, area_id=leg.area_id, reason=EmptySlotReason.DROPPED_LEG)


def _as_solve_input(block: CastBlock, interval: Interval) -> ShadowBlock:
    """One cast block, at the span this week holds of it, as the solve input's own shape.

    The binding is the block's own derivation from its origin and occurrence key and is not a
    function of the interval, so the two journeys one commitment casts keep the two identities
    that let an outcome name one of them even when a week holds part of one.
    """
    return ShadowBlock(
        binding=block.binding,
        interval=interval,
        area_id=block.area_id,
        title=block.title,
        anchor_type_name=block.anchor_type_name,
        anchor_title=block.anchor_title,
    )
