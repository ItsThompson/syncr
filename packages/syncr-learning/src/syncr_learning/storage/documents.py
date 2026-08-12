"""Turning the stored JSONB of a plan document and an edit context into the values above them.

Split from the reader because it is arithmetic over dictionaries and the reader is I/O. Every
function here takes what ``asyncpg`` handed back and answers with a value or with nothing, and
"nothing" is a reading rather than an exception: a nightly run over a year of correct rows must not
stop at one row it cannot rebuild, so an unreadable block is dropped and counted rather than thrown.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from syncr_common.logging import get_logger
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import Interval
from syncr_learning.facts import PlannedBlock
from syncr_learning.storage import spelling

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.zones import ZoneId

_log = get_logger("syncr.learning")


def planned_blocks(document: object) -> tuple[PlannedBlock, ...]:
    """Every block of a stored document this job can rebuild, in the order the document holds them.

    A block that cannot be rebuilt is dropped and reported. The alternatives are worse: raising
    would lose a whole tenant's night over one row, and defaulting a missing interval would invent a
    placement the user never had.
    """
    if not isinstance(document, dict):
        return ()
    unreadable = 0
    found: list[PlannedBlock] = []
    for stored in document.get(spelling.DOCUMENT_BLOCKS, []) or []:
        block = _block(stored)
        if block is None:
            unreadable += 1
            continue
        found.append(block)
    if unreadable:
        _log.warning("learning.document.block_unreadable", blocks=unreadable)
    return tuple(found)


def zone_by_date(document: object) -> dict[date, ZoneId]:
    """The zone profile the week was computed under, by local date.

    Empty for a document that captured none, which the hour resolution reads as "fall back to the
    instant's own hour". A week with no captured profile is one written before profiles were stored.
    """
    if not isinstance(document, dict):
        return {}
    stored = document.get(spelling.DOCUMENT_ZONE_BY_DATE) or {}
    if not isinstance(stored, dict):
        return {}
    resolved: dict[date, ZoneId] = {}
    for on, zone in stored.items():
        parsed = _date(on)
        if parsed is not None and isinstance(zone, str):
            resolved[parsed] = zone
    return resolved


def binding(stored: object) -> BindingRef | None:
    """The content identity a stored binding names, or nothing because it names none."""
    if not isinstance(stored, dict):
        return None
    kind = stored.get(spelling.BINDING_KIND)
    entity_id = _uuid(stored.get(spelling.BINDING_ENTITY_ID))
    occurrence_key = stored.get(spelling.BINDING_OCCURRENCE_KEY)
    if not isinstance(kind, str) or entity_id is None or not isinstance(occurrence_key, str):
        return None
    split_index = stored.get(spelling.BINDING_SPLIT_INDEX)
    try:
        return BindingRef(
            kind=BindingKind(kind),
            entity_id=entity_id,
            occurrence_key=occurrence_key,
            split_index=split_index if isinstance(split_index, int) else None,
        )
    except ValueError:
        return None


def measurement_delta(context: object) -> Mapping[str, float] | None:
    """The seven measurement differences a stored context carries, or nothing because it has none.

    ``None`` for every event written before the difference was measured. Those rows are the corpus
    and nothing prunes them, so the absence has to read as a value the weight fit can exclude.
    """
    if not isinstance(context, dict):
        return None
    stored = context.get(spelling.CONTEXT_MEASUREMENT_DELTA)
    if not isinstance(stored, dict):
        return None
    return {
        term: float(value)
        for term, value in stored.items()
        if isinstance(term, str) and isinstance(value, int | float) and not isinstance(value, bool)
    }


def inside_off_plan(context: object) -> bool:
    """The off-plan flag, as the stored context carries it. Absent reads as false, the older row's
    shape."""
    return bool(isinstance(context, dict) and context.get(spelling.CONTEXT_INSIDE_OFF_PLAN))


def _block(stored: object) -> PlannedBlock | None:
    if not isinstance(stored, dict):
        return None
    interval = _interval(stored.get(spelling.BLOCK_INTERVAL))
    identity = binding(stored.get(spelling.BLOCK_BINDING))
    if interval is None or identity is None:
        return None
    return PlannedBlock(
        binding=identity,
        interval=interval,
        area_id=_uuid(stored.get(spelling.BLOCK_AREA_ID)),
    )


def _interval(stored: object) -> Interval | None:
    if not isinstance(stored, dict):
        return None
    start = _instant(stored.get(spelling.INTERVAL_START))
    end = _instant(stored.get(spelling.INTERVAL_END))
    if start is None or end is None or start >= end:
        return None
    return Interval(start, end)


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # A stored instant is written in UTC. One that arrived naive is normalised rather than compared
    # against a wall clock later, which is how a transition-week defect becomes invisible.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
