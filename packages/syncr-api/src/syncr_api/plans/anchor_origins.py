"""The feed behind each imported commitment on the week payload, and whether it is failing.

A stored block binds to the commitment it holds and not to the calendar source that commitment was
read from, so a surface could not tell a day fed by a failing feed from a healthy one without
reading the sources itself. This composes the answer once, here, with the same predicate the notice
composer applies, so the staleness threshold stays a server constant: a surface reads the answer
rather than computing staleness for itself.

Only a block bound to an import claims anything. A block the solver placed answers nothing, and so
does one whose commitment outlived its source: removing a source cascades to its commitments while
the stored weeks naming them stay, and a claim about a feed that no longer exists is not a claim
this read can check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.feed_notices import is_feed_stale
from syncr_domain.identity import BindingKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from syncr_api.calendars.records import CalendarSourceId, CalendarSourceRecord
    from syncr_domain.identifiers import AnchorId
    from syncr_domain.plan import Block

# The three binding kinds whose content IS an imported commitment, including the two buffers one
# casts. All three bind to the anchor row, which is what ties the block to a feed.
ANCHOR_BOUND_KINDS: Final[frozenset[BindingKind]] = frozenset(
    {BindingKind.ANCHOR, BindingKind.ANCHOR_PREP, BindingKind.ANCHOR_TRANSIT}
)


@dataclass(frozen=True, slots=True)
class AnchorOrigin:
    """Where an imported commitment came from, and whether that feed is failing now."""

    source_id: CalendarSourceId
    possibly_stale: bool


def bound_anchor_ids(blocks: Iterable[Block]) -> tuple[AnchorId, ...]:
    """The distinct commitments these blocks bind to, in the order first seen.

    Prep and transit bind to the same row their anchor does, so one commitment fed by one feed is
    collected once however many blocks of it the week holds.
    """
    found: dict[AnchorId, None] = {}
    for block in blocks:
        if block.binding.kind in ANCHOR_BOUND_KINDS:
            found.setdefault(block.binding.entity_id, None)
    return tuple(found)


def anchor_origins(
    sources_of_anchor: Mapping[AnchorId, CalendarSourceId],
    sources: Mapping[CalendarSourceId, CalendarSourceRecord],
    *,
    now: datetime,
) -> Mapping[AnchorId, AnchorOrigin]:
    """One origin per commitment whose feed this read can still name.

    A commitment whose source row is gone is left out rather than answered with a guess. The
    staleness half is the notice composer's own decision about the source, read at ``now``.
    """
    return {
        anchor_id: AnchorOrigin(
            source_id=source_id,
            possibly_stale=is_feed_stale(sources[source_id], now=now),
        )
        for anchor_id, source_id in sources_of_anchor.items()
        if source_id in sources
    }
