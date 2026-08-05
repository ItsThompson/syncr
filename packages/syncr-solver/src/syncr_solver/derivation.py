"""Every block and slot derivation determines, built from one week's resolved inputs.

Four kinds of block have a placement nobody chose: a routine occurrence, an imported commitment,
a buffer an anchor's type cast, and a concrete template entry. Each is built here, with the one
``bound`` clause naming what determined it, and with an identity derived from the week and the
binding rather than supplied.

**A slot becomes an empty slot rather than a block.** Its content is bound late, and at this
point nobody has looked at the backlog, so the reason is ``not_solved`` and the label the gutter
renders says the content has not been chosen. It deliberately does not borrow the wording of the
reason that reports an empty backlog: claiming the backlog is empty would state something no
code here computed.

## An occurrence is keyed by a date of this week, and the key is not parsed to prove it

A routine occurrence and a template entry are keyed by the local date they materialize on, and
the wall time a ``bound`` clause renders needs the zone active on that date. The mapping from
key to zone is derived FORWARD from the week's own dates, so this module holds no second parser
for the date form, and a key that names no date of the week is refused rather than read against
some other day's zone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.gaps import EmptySlot, EmptySlotReason
from syncr_domain.identity import BindingKind, BindingRef, date_occurrence_key
from syncr_domain.plan import Block
from syncr_domain.reasons import ReasonRecord
from syncr_domain.templates import TemplateEntryKind
from syncr_solver.clauses import (
    bound_to_anchor,
    bound_to_anchor_type,
    bound_to_routine,
    bound_to_template_entry,
)
from syncr_solver.errors import MaterializeError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_domain.reasons import Bound
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneId
    from syncr_solver.inputs import Anchor, FrameEntry, MaterializedEntry, ShadowBlock


def zone_by_occurrence(
    iso_week: IsoWeek, zone_by_date: Mapping[Date, ZoneId]
) -> Mapping[str, ZoneId]:
    """The zone active on each occurrence key a date-keyed binding of this week can hold.

    Derived by spelling each of the week's seven keys the way the producer spells them, which is
    the same derivation read in the same direction. A stored key is therefore compared for
    equality, never parsed, which is what keeps one definition of the date form.
    """
    return {date_occurrence_key(day): zone_by_date[day] for day in iso_week.dates()}


def frame_blocks(
    frame: Sequence[FrameEntry], *, iso_week: IsoWeek, zones: Mapping[str, ZoneId]
) -> tuple[Block, ...]:
    """One block per routine occurrence, at the effective duration it arrived at.

    Nothing here resizes a routine. The frame defines the space a week has rather than competing
    inside it, so a reduction is already in the interval and the minimum it was clamped to is the
    assembler's business.
    """
    return tuple(
        _block(
            iso_week=iso_week,
            binding=BindingRef(BindingKind.ROUTINE, entry.routine_id, entry.occurrence_key),
            interval=entry.interval,
            title=entry.title,
            clause=bound_to_routine(entry, zone=_zone_of(entry.occurrence_key, zones, "routine")),
        )
        for entry in frame
    )


def anchor_blocks(anchors: Sequence[Anchor], *, iso_week: IsoWeek) -> tuple[Block, ...]:
    """One block per imported commitment, at the time its publisher states.

    Unclipped and un-snapped: an anchor's duration is the source's fact rather than this week's
    reading of it, and an imported fact keeps its real time.
    """
    return tuple(
        _block(
            iso_week=iso_week,
            binding=BindingRef.for_anchor(anchor.anchor_id),
            interval=anchor.interval,
            title=anchor.title,
            clause=bound_to_anchor(anchor),
        )
        for anchor in anchors
    )


def shadow_blocks(shadows: Sequence[ShadowBlock], *, iso_week: IsoWeek) -> tuple[Block, ...]:
    """One block per prep or transit buffer, carrying the Area its anchor's type named.

    A block rather than a window because it carries an Area: it is discretionary time allocated
    to that Area in the same way a task is. A buffer whose type named no Area arrives as a
    forbidden window instead, and windows are not blocks.
    """
    return tuple(
        _block(
            iso_week=iso_week,
            binding=shadow.binding,
            interval=shadow.interval,
            title=shadow.title,
            area_id=shadow.area_id,
            clause=bound_to_anchor_type(shadow),
        )
        for shadow in shadows
    )


def entry_blocks(
    entries: Sequence[MaterializedEntry], *, iso_week: IsoWeek, zones: Mapping[str, ZoneId]
) -> tuple[Block, ...]:
    """One block per CONCRETE template entry, named by the content the entry binds.

    A slot is not here. It carries no content identity and no name, so what it becomes is an
    empty slot rather than a block with nothing in it.
    """
    return tuple(
        _entry_block(entry, iso_week=iso_week, zones=zones)
        for entry in entries
        if entry.kind is TemplateEntryKind.CONCRETE
    )


def empty_slots(entries: Sequence[MaterializedEntry]) -> tuple[EmptySlot, ...]:
    """One empty slot per template SLOT, stating that its content is not yet chosen.

    Every slot, unconditionally: nobody looked at the backlog, so no slot can report anything
    that was computed about content. Left at its declared time and duration, because shrinking it
    would read as the solver editing the user's template.
    """
    return tuple(
        EmptySlot(
            interval=entry.interval,
            area_id=entry.area_id,
            reason=EmptySlotReason.NOT_SOLVED,
        )
        for entry in entries
        if entry.kind is TemplateEntryKind.SLOT
    )


def _entry_block(
    entry: MaterializedEntry, *, iso_week: IsoWeek, zones: Mapping[str, ZoneId]
) -> Block:
    title = entry.title
    if title is None:  # pragma: no cover - the struct requires a concrete entry to carry one
        raise MaterializeError(
            f"template entry {entry.entry_id} names its content and carries no title: the block "
            "an entry becomes renders the resolved content name"
        )
    zone = _zone_of(entry.occurrence_key, zones, "template_entry")
    return _block(
        iso_week=iso_week,
        binding=BindingRef(BindingKind.TEMPLATE_ENTRY, entry.entry_id, entry.occurrence_key),
        interval=entry.interval,
        title=title,
        area_id=entry.area_id,
        clause=bound_to_template_entry(entry, title=title, zone=zone),
    )


def _block(
    *,
    iso_week: IsoWeek,
    binding: BindingRef,
    interval: Interval,
    title: str,
    clause: Bound,
    area_id: AreaId | None = None,
) -> Block:
    """One derived block: its span, its identity, and the single clause that explains it.

    ``pinned`` stays false for every block built here. A placement determined by derivation was
    never moved off another one, so it carries no pin glyph and is not a training label, even
    though the solver may not move it either.
    """
    return Block(
        iso_week=iso_week,
        interval=interval,
        binding=binding,
        title=title,
        reason=ReasonRecord((clause,)),
        area_id=area_id,
    )


def _zone_of(occurrence_key: str, zones: Mapping[str, ZoneId], kind: str) -> ZoneId:
    """The zone the occurrence this key names was resolved in.

    A key absent from the mapping names a date the week does not hold, which is the producer
    keying an occurrence against another week. Refused rather than read against a neighbouring
    day's zone: which week owns an occurrence is the producer's question, and answering it here
    would hide a producer that answered it wrongly.
    """
    zone = zones.get(occurrence_key)
    if zone is None:
        raise MaterializeError(
            f"a {kind!r} occurrence keyed {occurrence_key!r} names no date of this week: the key "
            "is the local date the occurrence materializes on, and the zone its wall times were "
            "resolved in is that date's"
        )
    return zone
