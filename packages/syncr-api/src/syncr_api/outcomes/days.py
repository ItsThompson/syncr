"""Which instants a local day covers, and which of a week's blocks belong to it.

Two rules, and both are about a boundary this epic has already paid for.

**A local day is midnight to midnight, resolved per date.** That is
:func:`syncr_api.calendars.day_spans.local_day_span`, which every all-day span already reads, and
it is used here rather than restated: a day is 23 hours long on a spring-forward date, 25 on a
fall-back date, and any length at all across a travel boundary. Consecutive days taken from it
abut exactly, because one day's end and the next day's start are the same expression of the same
midnight, so a block falls in exactly one day and no block can fall in none.

**A date that names no span does not exist, and saying so is the answer.** ``Pacific/Apia`` skipped
30 December 2011 entirely, and a travel override moving a clock far enough east does the same to a
date the user names: local midnight on the date and local midnight on the next resolve to one
instant, and an interval needs its start before its end. The refusal is the honest answer, because
there is no day to render and nothing to confirm.

**A block belongs to the day its interval STARTS in.** A night's sleep runs from Sunday 23:00 to
Monday 07:00 and is listed on Sunday. The alternative, listing a block on every day it touches,
makes one block confirmable twice and settles it on whichever day the user answered for first,
which is a second answer to "what happened to this". Starting-in also keeps the read to one week's
plan of record: a local date lies in exactly one ISO week, so a block that starts inside it was
placed by that week's plan.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from syncr_api.calendars.day_spans import local_day_span
from syncr_domain.intervals import IntervalError

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.zones import Date, ZoneProfile

ONE_DAY = timedelta(days=1)

# One day, which is what every span here covers. `local_day_span` takes a count because an
# all-day event may cover several; a ledger reads one date at a time.
_ONE = 1


def day_span(on: Date, profile: ZoneProfile) -> Interval | None:
    """The instants ``on`` covers in this tenant's zones, or ``None`` when the date does not exist.

    ``None`` rather than a raised error, so the caller decides what an absent day means: a read
    answers 422 naming the date, and a range walk skips it.
    """
    try:
        return local_day_span(on, _ONE, profile)
    except IntervalError:
        return None


def dates_in(first: Date, last: Date) -> Iterator[Date]:
    """Every date from ``first`` to ``last``, both included."""
    on = first
    while on <= last:
        yield on
        on += ONE_DAY


def blocks_of_the_day(document: PlanDocument | None, span: Interval) -> tuple[Block, ...]:
    """The blocks that begin inside ``span``, earliest first.

    Prep and transit blocks are here with every other kind. They are blocks carrying an Area, not
    bands, so they appear in the ledger, they can be confirmed, and they carry outcomes.
    """
    blocks = () if document is None else document.blocks
    return tuple(sorted(_beginning_inside(blocks, span), key=_ledger_order))


def _beginning_inside(blocks: Sequence[Block], span: Interval) -> Iterator[Block]:
    return (block for block in blocks if span.start <= block.interval.start < span.end)


def _ledger_order(block: Block) -> tuple[object, ...]:
    """Time order, then a total tie-break, so two reads of one day emit one order.

    The title is not enough: two blocks can share an interval and a title, and the binding is what
    tells them apart. Two reads of unchanged data have to agree, or a ledger reorders itself under
    the user between the read and the action they take on it.
    """
    return (
        block.interval.start,
        block.interval.end,
        block.title,
        block.binding.kind.value,
        f"{block.binding.entity_id}\x1f{block.binding.occurrence_key}",
    )
