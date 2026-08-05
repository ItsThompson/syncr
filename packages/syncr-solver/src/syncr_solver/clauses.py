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
clause can name. Four pieces of the upstream examples are absent from those inputs and are
therefore absent here: the day type a shape belongs to, a routine's day-type association, which
does not exist at all because a routine materializes on every date, the calendar and access role
an anchor was read from, and the name of the anchor type that cast a buffer along with the title
of the commitment it was cast by, which is reachable INSIDE THIS STRUCT only through a join that
is not total: an evening buffer for a Monday-morning commitment is cast by an anchor that this
week's span does not hold.

So each label states the determinant's own name plus the geometry the block was derived at, and
a clause never renders a value that depends on whether an unrelated collection happens to carry
a row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_domain.budgets import MINUTES_PER_HOUR
from syncr_domain.identity import BindingKind, TransitLeg
from syncr_domain.reasons import Bound, DerivationSource
from syncr_domain.zones import resolve_zone

if TYPE_CHECKING:
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.zones import ZoneId
    from syncr_solver.inputs import Anchor, FrameEntry, MaterializedEntry, ShadowBlock

# The separator the panel's rows already use between a determinant and its geometry.
_PART = " · "

# How a buffer says which journey it is. A prep buffer needs no discriminator, and the two
# transit legs need one, which is the key their binding carries.
_LEG_LABEL: Final = {TransitLeg.OUT: "transit out", TransitLeg.BACK: "transit back"}


def bound_to_routine(entry: FrameEntry, *, zone: ZoneId) -> Bound:
    """What a frame block says: the routine, and the occurrence's declared shape.

    The duration is the EFFECTIVE one the assembler clamped to, which is the whole of what the
    frame is: a routine reduced by an approved concession says so by being shorter.
    """
    geometry = f"{_wall_time(entry.interval.start, zone)} + {duration_label(entry.interval)}"
    return Bound(DerivationSource.ROUTINE, _PART.join((entry.title, geometry)))


def bound_to_template_entry(entry: MaterializedEntry, *, title: str, zone: ZoneId) -> Bound:
    """What a concrete template entry's block says: its content, at the shape's target time.

    The title is an argument rather than a read of ``entry.title``, because only a concrete entry
    carries one and this clause is only ever built for a concrete entry. The caller separating
    the two kinds is what already knows which it holds.
    """
    return Bound(
        DerivationSource.TEMPLATE_ENTRY, _PART.join((title, _wall_time(entry.interval.start, zone)))
    )


def bound_to_anchor(anchor: Anchor) -> Bound:
    """What an imported commitment's block says, which is the title the week was read against.

    Stored rather than re-read, so a commitment retitled in March does not change what a week
    approved in February says.
    """
    return Bound(DerivationSource.ANCHOR, anchor.title)


def bound_to_anchor_type(shadow: ShadowBlock) -> Bound:
    """What a prep or transit block says: which buffer it is, and how long the type reserves.

    The geometry is read from the block rather than from the type's declaration, so a buffer
    truncated by a collision with an earlier one reports the time it actually holds.
    """
    geometry = f"{_buffer_label(shadow.binding)}, {duration_label(shadow.interval)}"
    return Bound(DerivationSource.ANCHOR_TYPE, _PART.join((shadow.title, geometry)))


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


def _buffer_label(binding: BindingRef) -> str:
    """Which of the three buffers an anchor's type casts this block is.

    The leg is read back from the key its own constructor spelled, through the closed vocabulary
    that defines it, so there is one definition of what the two legs are called.
    """
    if binding.kind is BindingKind.ANCHOR_PREP:
        return "prep"
    return _LEG_LABEL[TransitLeg(binding.occurrence_key)]
