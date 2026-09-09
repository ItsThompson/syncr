"""The ``bound`` clause a derived block carries, and the labels it renders from.

``materialize`` runs no search, evaluates no objective and reads no weight set, so five of the
six clause kinds have nothing to draw on. ``bound`` is the sixth, widened to accept a derivation
source alongside a habit's binding sources, which is what lets every derived block satisfy the
one-clause minimum without an exception being carved into it.

**One clause per block, and the clause names the determinant.** A routine, a concrete template
entry, an imported commitment, or the anchor type that cast a buffer. The panel renders the
source and then this text, so the text is what the reader learns beyond the block's own span.

## What the text can say, and what it cannot

Every label here is derived from the resolved inputs and from nothing else, which bounds what a
clause can name. Two pieces of the upstream examples are absent from those inputs and are
therefore absent here: a routine's day-type association, which does not exist at all because a
routine materializes on every date, and the calendar and access role an anchor was read from.

So each label states the determinant's own name plus the geometry the block was derived at, and
a clause never renders a value that depends on whether an unrelated collection happens to carry
a row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.budgets import MINUTES_PER_HOUR
from syncr_domain.reasons import Bound, DerivationSource
from syncr_domain.zones import resolve_zone

if TYPE_CHECKING:
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.zones import ZoneId
    from syncr_solver.inputs import Anchor, FrameEntry, MaterializedEntry, ShadowBlock

# The separator the panel's rows already use between a determinant and its geometry.
_PART = " · "


def bound_to_routine(entry: FrameEntry, *, zone: ZoneId) -> Bound:
    """What a frame block says: the routine, and the occurrence's declared shape.

    The duration is the EFFECTIVE one the assembler clamped to, which is the whole of what the
    frame is: a routine reduced by an approved concession says so by being shorter.
    """
    geometry = f"{_wall_time(entry.interval.start, zone)} + {duration_label(entry.interval)}"
    return Bound(DerivationSource.ROUTINE, _PART.join((entry.title, geometry)))


def bound_to_template_entry(entry: MaterializedEntry, *, title: str, zone: ZoneId) -> Bound:
    """What a concrete template entry's block says: its day shape, its content, at the target time.

    The day type's name leads because it is what placed the content and it is the one thing the
    block's own title cannot say. ``title`` itself is an argument rather than a read of
    ``entry.title``, because only a concrete entry carries one and this clause is only ever built
    for a concrete entry. The caller separating the two kinds is what already knows which it holds.
    """
    return Bound(
        DerivationSource.TEMPLATE_ENTRY,
        _PART.join((entry.day_type_name, title, _wall_time(entry.interval.start, zone))),
    )


def bound_to_anchor(anchor: Anchor) -> Bound:
    """What an imported commitment's block says, which is the title the week was read against.

    Stored rather than re-read, so a commitment retitled in March does not change what a week
    approved in February says.
    """
    return Bound(DerivationSource.ANCHOR, anchor.title)


def bound_to_anchor_type(shadow: ShadowBlock) -> Bound:
    """What a prep or transit block says: the type and commitment that determined it.

    Both values are resolved before the buffer is clipped to a week, so a boundary-crossing
    buffer has the same clause in either week that holds part of it.
    """
    return Bound(
        DerivationSource.ANCHOR_TYPE,
        _PART.join((shadow.anchor_type_name, shadow.anchor_title)),
    )


def duration_label(interval: Interval) -> str:
    """A span's elapsed length, as the hours and minutes a reader says out loud."""
    hours, minutes = divmod(interval.total_minutes(), MINUTES_PER_HOUR)
    if hours and minutes:
        return f"{hours}h{minutes}m"
    return f"{hours}h" if hours else f"{minutes}m"


def _wall_time(instant: Instant, zone: ZoneId) -> str:
    """The clock time ``instant`` reads at in ``zone``, which is what the user declared.

    Rendered in the zone active on the occurrence's own date, so a week spanning a travel
    boundary reports each occurrence at the time its own day was declared for.
    """
    return instant.astimezone(resolve_zone(zone)).strftime("%H:%M")
