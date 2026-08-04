"""Turning one anchor plus the type it carries into the shadows that anchor casts.

The arithmetic, in full, over the anchor's own interval and the type's two leads and four
durations. Every span is elapsed time from an instant the publisher chose, so nothing here
resolves a wall time and nothing here needs a zone:

    prep         = [start - prep_lead,     start - prep_lead + prep_duration)
    transit_out  = [start - transit_lead,  start - transit_lead + transit_duration)
    transit_back = [end,                   end + return_transit)
    recovery     = [end,                   end + post_buffer)

Four consequences of that shape are worth stating, because each is a decision rather than a
detail.

**A lead is elapsed time, not a wall-clock offset.** A lead crossing a daylight-saving
transition therefore lands at a different wall time than the same lead on an ordinary day: a
14-hour lead back across a spring-forward gap starts an hour earlier by the clock on the wall.
A lead crossing a day or a week boundary is likewise permitted and needs no special case, which
is what puts the evening before's prep in the previous ISO week.

**Recovery is measured from the anchor's end, never from the end of a return leg.** So a return
leg and a recovery window both start at the same instant and overlap by construction, and the
exemption that makes the journey home legal is stated on the set that holds both.

**A buffer is not snapped to the grid.** An imported commitment keeps its real time, even at
``:07``, and a buffer derived from one is computed from that real time, seconds included. The
grid's step has exactly one part to play in this geometry, and it is not here: it is the shortest
block a surface can draw, so :mod:`syncr_api.anchors.shadow_collisions` uses it as the floor
below which a truncated block is dropped rather than as a target anything is moved to.

**Clipping is not here.** These spans are unclipped, so a Monday-morning commitment casts its
Sunday-evening prep whatever week is being assembled. Which of them fall inside a week, and how
far back the anchors have to be read for none to be missed, are questions only the caller
holding the week's span can answer.

Two of the strings this module composes are the records' own and two are not, which is worth stating
rather than leaving for a reader to compare. ``Prep for {commitment}`` and ``Go Home`` are what
``docs/design/scratch/block-states.html`` renders. The outbound leg's rendered ``Leave for Uni``
names a **destination nothing in the product carries**: transit is declared per anchor type rather
than derived from a location, so the leg names the commitment it is a journey to instead. And the
recovery band's rendered ``no deep work · recovery`` states a **consequence of the scope** rather
than the commitment: which Areas count as deep work is not something a declaration says, and a
window's label has to survive being read months later, so the stored label names the reason and the
commitment that reserved the time. What a surface draws beside the band is that surface's own
wording; what the document stores is this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from syncr_api.anchors.records import ShadowDeclaration
from syncr_api.anchors.shadow_collisions import without_collisions
from syncr_api.anchors.shadow_products import ShadowBlock, ShadowSet
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.identity import NO_OCCURRENCE, Origin, TransitLeg
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from syncr_api.anchors.records import AnchorRecord, AnchorTypeRecord, AnchorTypeSpecification
    from syncr_domain.identifiers import AnchorId, AreaId
    from syncr_domain.intervals import Instant

# What a buffer is called once it is a block. Neither the declaration nor the commitment names a
# destination, so the outbound leg names the commitment it is a journey to; the return leg needs no
# name at all, because home is where every one of them ends.
PREP_TITLE: Final = "Prep for {commitment}"
OUTBOUND_TITLE: Final = "Leave for {commitment}"
RETURN_TITLE: Final = "Go Home"

# What a buffer is called once it is a window instead. A window explains a gap, so it reads as
# the reason the time is reserved followed by the commitment that reserved it, which is the
# wording the pure package already uses for an off-plan gutter label.
LABEL: Final = "{reason} · {commitment}"
REASON_BY_KIND: Final[Mapping[ForbiddenKind, str]] = {
    ForbiddenKind.RECOVERY: "recovery",
    ForbiddenKind.PREP_UNATTRIBUTED: "prep",
    ForbiddenKind.TRANSIT_UNATTRIBUTED: "transit",
}


class ShadowPairingRejected(ValueError):
    """An anchor paired with a type it does not carry, so no shadow may be cast from it."""


@dataclass(frozen=True, slots=True)
class TypedAnchor:
    """One anchor and the type it carries, as the caller resolved the pair.

    ``anchor_type`` is ``None`` for an untyped anchor, and that pairing is representable because
    a regeneration reads every anchor a span holds rather than only the typed ones. An untyped
    commitment is opaque busy time: it casts nothing, and syncr makes no assumption about it.
    """

    anchor: AnchorRecord
    anchor_type: AnchorTypeRecord | None


def generate(anchor: AnchorRecord, anchor_type: AnchorTypeRecord | None) -> ShadowSet:
    """The shadows ``anchor`` casts under the type it carries, unclipped.

    Empty for an untyped anchor, and empty for a type whose every member is zero: a zero on any
    member collapses that product, which is asked of the declaration rather than re-derived
    here so the two statements cannot disagree.
    """
    _require_the_type_the_anchor_carries(anchor, anchor_type)
    if anchor_type is None:
        return ShadowSet.EMPTY
    specification = anchor_type.specification
    declared = ShadowDeclaration.of(specification)
    blocks: list[ShadowBlock] = []
    forbidden: list[ForbiddenWindow] = []
    for buffer in _declared_buffers(anchor, specification, declared):
        # The one rule, in the one place it decides anything: a buffer with an Area belongs to
        # that Area and is a block, and a buffer with none has nothing to charge its minutes to,
        # so what it explains is that nothing may be there.
        if buffer.area_id is None:
            forbidden.append(_window(anchor, buffer.interval, buffer.unattributed_kind))
        else:
            blocks.append(
                ShadowBlock(
                    interval=buffer.interval,
                    origin=buffer.origin,
                    occurrence_key=buffer.occurrence_key,
                    area_id=buffer.area_id,
                    title=buffer.title,
                    anchor_id=anchor.id,
                )
            )
    if declared.recovery:
        forbidden.append(_recovery(anchor, specification))
    return ShadowSet(blocks=tuple(blocks), forbidden=tuple(forbidden))


def regenerate(anchors: Sequence[TypedAnchor]) -> ShadowSet:
    """Every shadow ``anchors`` cast, as one set, with colliding blocks resolved.

    Wholesale by construction: it reads no previous set, so an anchor that moved, an anchor that
    was retyped, and a type that was edited are all answered by generating again rather than by
    patching what a previous generation produced. One anchor's regeneration is therefore equal
    to generating that anchor on its own, and that equality is a consequence of a boundary rule
    rather than of this function: only this path resolves collisions, and a declaration whose own
    prep ran into its own outbound leg is refused where it is written, by
    :func:`syncr_api.anchors.rules.require_prep_clear_of_transit` and by the check constraint that
    says it again on the table. Relax either and one commitment could collide with itself, which
    :func:`generate` would answer and this function would resolve.

    Windows are contributed whole, because nothing is scheduled in one: two commitments
    reserving overlapping time is a union rather than a contest, and the union is taken where
    the spans are read. Blocks are the members that cannot both stand.
    """
    generated = [
        (pair, generate(pair.anchor, pair.anchor_type)) for pair in sorted(anchors, key=_cast_order)
    ]
    return ShadowSet(
        blocks=without_collisions([shadows.blocks for _, shadows in generated]),
        forbidden=tuple(window for _, shadows in generated for window in shadows.forbidden),
    )


@dataclass(frozen=True, slots=True)
class _Buffer:
    """One declared buffer, before the Area it names decides what it becomes."""

    interval: Interval
    origin: Origin
    occurrence_key: str
    area_id: AreaId | None
    title: str
    unattributed_kind: ForbiddenKind


def _declared_buffers(
    anchor: AnchorRecord, specification: AnchorTypeSpecification, declared: ShadowDeclaration
) -> Iterator[_Buffer]:
    """The prep and transit buffers this type declares, in the order they run.

    A product the declaration collapsed is not yielded, so no interval is built from a zero
    duration: the interval algebra refuses a zero-length span by construction, and that refusal
    is the arithmetic's own statement that a collapsed product has no span at all.
    """
    start, end = anchor.interval.start, anchor.interval.end
    if declared.prep:
        prep_start = start - timedelta(minutes=specification.prep_lead_minutes)
        yield _Buffer(
            interval=_from(prep_start, specification.prep_duration_minutes),
            origin=Origin.PREP,
            occurrence_key=NO_OCCURRENCE,
            area_id=specification.prep_area_id,
            title=PREP_TITLE.format(commitment=anchor.title),
            unattributed_kind=ForbiddenKind.PREP_UNATTRIBUTED,
        )
    if declared.outbound_transit:
        # The nullable lead read through the one property that applies the abutting default. Read
        # from the field, a null lead would place the journey AT the commitment rather than
        # before it.
        leaves = start - timedelta(minutes=specification.effective_transit_lead_minutes)
        yield _Buffer(
            interval=_from(leaves, specification.transit_duration_minutes),
            origin=Origin.TRANSIT,
            occurrence_key=TransitLeg.OUT.value,
            area_id=specification.transit_area_id,
            title=OUTBOUND_TITLE.format(commitment=anchor.title),
            unattributed_kind=ForbiddenKind.TRANSIT_UNATTRIBUTED,
        )
    if declared.return_transit:
        yield _Buffer(
            interval=_from(end, specification.return_transit_minutes),
            origin=Origin.TRANSIT,
            occurrence_key=TransitLeg.BACK.value,
            area_id=specification.transit_area_id,
            title=RETURN_TITLE,
            unattributed_kind=ForbiddenKind.TRANSIT_UNATTRIBUTED,
        )


def _recovery(anchor: AnchorRecord, specification: AnchorTypeSpecification) -> ForbiddenWindow:
    """The window after the commitment. Always a window, whatever Areas the type names.

    A recovery buffer has no Area to belong to even when the type names some: the Areas it names
    are the ones it FORBIDS, which is the opposite relationship. So this is the one product the
    block-or-window rule does not decide.
    """
    return ForbiddenWindow(
        interval=_from(anchor.interval.end, specification.post_buffer_minutes),
        kind=ForbiddenKind.RECOVERY,
        scope=(ForbiddenScope.AREAS if specification.forbids_named_areas else ForbiddenScope.ALL),
        forbidden_area_ids=specification.forbidden_area_ids,
        label=_label(ForbiddenKind.RECOVERY, anchor.title),
        anchor_id=anchor.id,
    )


def _window(anchor: AnchorRecord, interval: Interval, kind: ForbiddenKind) -> ForbiddenWindow:
    """A prep or transit buffer with no Area, which forbids every Area for that reason."""
    return ForbiddenWindow(
        interval=interval,
        kind=kind,
        scope=ForbiddenScope.ALL,
        forbidden_area_ids=(),
        label=_label(kind, anchor.title),
        anchor_id=anchor.id,
    )


def _label(kind: ForbiddenKind, title: str) -> str:
    return LABEL.format(reason=REASON_BY_KIND[kind], commitment=title)


def _from(start: Instant, minutes: int) -> Interval:
    """The span of ``minutes`` beginning at ``start``."""
    return Interval(start, start + timedelta(minutes=minutes))


def _require_the_type_the_anchor_carries(
    anchor: AnchorRecord, anchor_type: AnchorTypeRecord | None
) -> None:
    """The pair has to agree, because both ways of disagreeing produce a fiction.

    A type supplied for an anchor that carries another one reserves time around a commitment
    for reasons belonging to a different one. No type supplied for an anchor that carries one
    silently loses that commitment's prep, transit and recovery, which reads on the grid as a
    type the user never declared.
    """
    carried = anchor.anchor_type_id
    supplied = None if anchor_type is None else anchor_type.id
    if carried == supplied:
        return
    raise ShadowPairingRejected(
        f"anchor {anchor.id} carries type {carried} and was paired with {supplied}: a shadow is "
        "the type's declaration measured from the commitment's own time, so a pair that does "
        "not agree casts one commitment's buffers around another's"
    )


def _cast_order(pair: TypedAnchor) -> tuple[Interval, AnchorId]:
    """The order the commitments occur in, which is the order their shadows are cast in.

    Total rather than nearly total: two commitments genuinely can occupy one span, and the
    identifier settles which of them keeps a block when their shadows collide, so the answer
    does not depend on which order the caller happened to read them in.
    """
    return (pair.anchor.interval, pair.anchor.id)
