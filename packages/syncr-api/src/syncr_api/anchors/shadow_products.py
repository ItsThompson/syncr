"""What a shadow IS once it has been generated: blocks with an Area, and windows without one.

One rule produces both kinds, and it is stated in :mod:`syncr_api.anchors.shadows` where the
buffers are built: **a buffer with an Area is a block, a buffer without one is a forbidden
window, and recovery is always a window.** This module holds what that rule produces and the
questions a reader asks of it.

``ShadowBlock`` is a buffer that found an Area, and it is deliberately not a plan
:class:`syncr_domain.plan.Block`. A block belongs to one ISO week and states the reason it is
where it is; a shadow is generated from one anchor with no week in view and no reason yet, so
the two are different shapes and the week assembler is what turns one into the other. What the
buffer does carry is the pair a ``BlockId`` is derived from: the origin, which fixes the binding
kind, and the occurrence key, which separates an anchor's two journeys from each other.

A shadow block is **fixed by derivation rather than pinned**. Nothing here says so, because
there is no field for it: pinning is the user's own edit, and a derived buffer carries no
placement it replaced.

``ShadowSet`` normalizes on construction, so every producer emits one order and two sets built
from the same shadows are equal. That is what lets a regeneration be compared against a fresh
generation as values rather than member by member.

**The title is not judged here.** A block's title rule has one home, on the plan block, and a
shadow's title is composed from the anchor's stored title, which the ingest boundary already
trimmed, scrubbed and made non-empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final

from syncr_domain.discretionary import SUBTRAHEND_BY_KIND, Subtrahend
from syncr_domain.errors import DomainError
from syncr_domain.identity import BindingRef, Origin, binding_kind_of
from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from syncr_domain.gaps import ForbiddenWindow
    from syncr_domain.identifiers import AnchorId, AreaId
    from syncr_domain.intervals import Interval

# The two origins a buffer can take. An anchor casts prep and transit and nothing else, and the
# umbrella word for all three products is *shadow*, which is why neither of them is spelled
# that way.
DERIVED_ORIGINS: Final = frozenset({Origin.PREP, Origin.TRANSIT})


class ShadowRejected(DomainError):
    """A shadow block names a product an anchor cannot cast."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ShadowBlock:
    """One prep or transit buffer that had an Area to belong to, so it is a block.

    ``occurrence_key`` is empty for prep, which happens once per anchor, and names the leg for
    transit. Without it the two journeys one anchor casts would derive one identity between
    them, so marking the outbound leg skipped would attach to the return leg as well.
    """

    interval: Interval
    origin: Origin
    occurrence_key: str
    area_id: AreaId
    title: str
    anchor_id: AnchorId

    def __post_init__(self) -> None:
        _require_a_derived_origin(self.origin)
        # Built for its rules rather than for its value: the binding is the one statement of
        # which occurrence keys a kind may take, and a key it refuses names another block.
        _ = self.binding

    @property
    def binding(self) -> BindingRef:
        """The content identity a plan block built from this buffer carries.

        Derived from the origin rather than chosen, because the binding vocabulary and the
        origin vocabulary are two readings of the same case and the mapping between them is
        stated once in the pure package.
        """
        return BindingRef(binding_kind_of(self.origin), self.anchor_id, self.occurrence_key)


@dataclass(frozen=True, slots=True, kw_only=True)
class ShadowSet:
    """Everything one or more anchors cast: blocks with an Area, windows without one.

    Members are held in one order whatever order they were built in: blocks by interval, and
    windows by interval then kind, so two anchors ending at the same instant cannot make one
    set differ from another that holds the same shadows.
    """

    blocks: tuple[ShadowBlock, ...] = ()
    forbidden: tuple[ForbiddenWindow, ...] = ()

    EMPTY: ClassVar[ShadowSet]

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", tuple(sorted(self.blocks, key=_block_order)))
        object.__setattr__(self, "forbidden", tuple(sorted(self.forbidden, key=_window_order)))

    def absolute_forbidden(self) -> IntervalSet:
        """The spans no Area may claim, unioned.

        Read through the pure package's subtraction table rather than by re-reading a scope, so
        which kinds leave the discretionary denominator has one statement. Unioned rather than
        listed because two adjacent commitments routinely reserve overlapping time, and summing
        those durations would subtract the shared part twice.
        """
        return IntervalSet(
            window.interval
            for window in self.forbidden
            if SUBTRAHEND_BY_KIND.get(window.occupancy_kind) is Subtrahend.ABSOLUTE_FORBIDDEN
        )

    def forbidden_for(self, area_id: AreaId) -> IntervalSet:
        """The spans this Area may not be scheduled in, unioned.

        Asked per Area because a recovery window scoped to named Areas forbids those and leaves
        the time available to every other one. A window that forbids everything forbids this
        Area too, which is the window's own reading of its scope rather than a second one here.
        """
        return IntervalSet(window.interval for window in self.forbidden if window.forbids(area_id))

    def forbidding_window(self, block: ShadowBlock) -> ForbiddenWindow | None:
        """The window that forbids ``block`` where it is, or ``None`` when none does.

        **An anchor's own derived blocks are exempt from the window that anchor cast.** Recovery
        is measured from the anchor's end and so is the return leg, so the two overlap by
        construction: without the exemption a commitment's own journey home would violate the
        window the same commitment reserved.

        The window rather than a yes, so a rejection can name the commitment that reserved the
        time. The first in the set's order when several forbid it, because one clause names one.
        """
        return next(
            (
                window
                for window in self.forbidden
                if window.anchor_id != block.anchor_id
                and window.forbids(block.area_id)
                and window.interval.overlaps(block.interval)
            ),
            None,
        )


def _require_a_derived_origin(origin: Origin) -> None:
    """An anchor casts prep and transit, and a shadow block is one of those two."""
    if origin in DERIVED_ORIGINS:
        return
    spelled = ", ".join(sorted(derived.value for derived in DERIVED_ORIGINS))
    raise ShadowRejected(
        f"an anchor casts {spelled}, and {origin.value!r} is neither: a shadow block is a "
        "buffer derived from a commitment, not content the solver placed"
    )


def _block_order(block: ShadowBlock) -> tuple[Interval, str]:
    return (block.interval, block.occurrence_key)


def _window_order(window: ForbiddenWindow) -> tuple[Interval, str, AnchorId]:
    return (window.interval, window.kind.value, window.anchor_id)


# Assigned once the ordering both members are normalized by is defined, because the empty set is
# built through the same constructor everything else is.
ShadowSet.EMPTY = ShadowSet()
