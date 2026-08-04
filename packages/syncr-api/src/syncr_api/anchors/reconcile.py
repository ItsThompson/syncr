"""Reconciliation: turning what a feed just published into the anchors a tenant holds.

Keyed on ``(source_id, external_uid)`` and nothing else. Not on the title and the time, because
a lecture moved by an hour is the same commitment at a new time, and diffing on its content
would read that as one commitment cancelled and another created: every block the first
displaced would be freed and then displaced again, and a plan would churn once per room change.

**Only a successful read removes an anchor.** A feed that could not be read and a feed that
answered "unchanged" both produce an empty event list, so removing on an empty list would clear
every anchor of a healthy feed that had nothing new to say. The caller distinguishes the three
attempts and calls the matching method; this module never has to guess.

**Typing happens here, not afterwards.** A created anchor is matched against the tenant's rules
in one pass, and an occurrence of a series the user has already retyped inherits that override
instead. Doing it in a second pass would leave a window in which an anchor existed with no type,
and any reader in that window would see opaque busy time where a shadow belongs.

**A series override is read before anything is written.** The overrides a tenant holds are read
off the occurrences that carry them, so they have to be read while those occurrences still
exist: as the horizon rolls forward, old occurrences of a daily standup drop out of every feed
and new ones arrive, and reading first is what carries the override across that turnover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.anchors.identity import (
    reconciliation_key,
    series_key,
    stored_location,
    stored_title,
)
from syncr_api.anchors.matching import first_match, series_overrides
from syncr_api.calendars.anchor_writing import AnchorDelta
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.anchors.matching import SeriesOverrides
    from syncr_api.anchors.records import AnchorRecord, AnchorTypeId, AnchorTypeRecord
    from syncr_api.anchors.repository import AnchorRepository
    from syncr_api.anchors.type_repository import AnchorTypeRepository
    from syncr_api.calendars.events import FetchOutcome, RawEvent
    from syncr_api.calendars.records import CalendarSourceId, CalendarSourceRecord

_log = get_logger("syncr.anchors")


@dataclass(frozen=True, slots=True)
class _Assignment:
    """The type one incoming event resolves to, and where that answer came from."""

    anchor_type_id: AnchorTypeId | None
    overridden: bool


class AnchorReconciler:
    """One tenant's anchors, made to agree with what their sources publish."""

    def __init__(self, anchors: AnchorRepository, types: AnchorTypeRepository) -> None:
        self._anchors = anchors
        self._types = types

    @measured("anchors")
    async def reconcile(self, source: CalendarSourceRecord, outcome: FetchOutcome) -> AnchorDelta:
        """Make ``source``'s anchors match ``outcome``, and report what changed.

        Creates what is new, replaces the fact of what moved or was renamed, and removes what the
        feed no longer publishes. Every anchor it touches stops being possibly stale, because the
        source just confirmed it.
        """
        held = await self._anchors.list_for_source(source.id)
        by_key = {anchor.external_uid: anchor for anchor in held}
        overrides = series_overrides(held)
        types = await self._types.list_all()
        incoming = _keyed(outcome.events)

        created = 0
        updated = 0
        for key, event in incoming.items():
            existing = by_key.get(key)
            assignment = self._assign(source.id, event, types=types, overrides=overrides)
            if existing is None:
                await self._create(source.id, key, event, assignment)
                created += 1
                continue
            await self._update(existing, event, assignment)
            updated += 1

        removed = await self._anchors.remove_absent(source.id, keeping=set(incoming))
        delta = AnchorDelta(
            created=created,
            updated=updated,
            removed=removed,
            current=await self._anchors.count_for_source(source.id),
        )
        _log.info(
            "anchors.reconciled",
            tenant_id=str(source.tenant_id),
            source_id=str(source.id),
            **delta.as_log_fields(),
        )
        return delta

    @measured("anchors")
    async def confirm(self, source: CalendarSourceRecord) -> AnchorDelta:
        """Record that this source's anchors are current, without reparsing anything.

        The feed answered "unchanged", so the last parse still stands. Nothing is created and
        nothing is removed; anything a previous failure marked possibly stale is no longer stale,
        because the source has now answered.
        """
        cleared = await self._anchors.set_possibly_stale(source.id, stale=False)
        return AnchorDelta(current=await self._anchors.count_for_source(source.id), updated=cleared)

    @measured("anchors")
    async def mark_possibly_stale(self, source: CalendarSourceRecord) -> AnchorDelta:
        """Retain this source's anchors and mark them possibly stale.

        The feed could not be read. Nothing is removed: the occupancy read on the last success is
        still the best syncr has, and a feed being down is not evidence that a lecture was
        cancelled.
        """
        marked = await self._anchors.set_possibly_stale(source.id, stale=True)
        delta = AnchorDelta(
            marked_stale=marked, current=await self._anchors.count_for_source(source.id)
        )
        _log.warning(
            "anchors.possibly_stale",
            tenant_id=str(source.tenant_id),
            source_id=str(source.id),
            **delta.as_log_fields(),
        )
        return delta

    def _assign(
        self,
        source_id: CalendarSourceId,
        event: RawEvent,
        *,
        types: Sequence[AnchorTypeRecord],
        overrides: SeriesOverrides,
    ) -> _Assignment:
        """The type this event gets: its series' override if it has one, else the first match."""
        series = series_key(event.series_uid)
        if series is not None and series in overrides:
            return _Assignment(anchor_type_id=overrides[series], overridden=True)
        matched = first_match(types, title=stored_title(event.title), source_id=source_id)
        return _Assignment(anchor_type_id=matched, overridden=False)

    async def _create(
        self,
        source_id: CalendarSourceId,
        key: str,
        event: RawEvent,
        assignment: _Assignment,
    ) -> None:
        await self._anchors.create(
            source_id=source_id,
            external_uid=key,
            series_uid=series_key(event.series_uid),
            title=stored_title(event.title),
            interval=event.interval,
            location=stored_location(event.location),
            anchor_type_id=assignment.anchor_type_id,
            type_overridden=assignment.overridden,
        )

    async def _update(
        self, existing: AnchorRecord, event: RawEvent, assignment: _Assignment
    ) -> None:
        """Replace the fact, and keep the user's override if the anchor already carried one.

        An override on the anchor itself outranks the rules AND outranks the series lookup, so a
        retyped occurrence keeps its type when its title changes into something another rule
        would match. A rule match is recomputed, because the title it was derived from may have
        moved.
        """
        if existing.type_overridden:
            assignment = _Assignment(anchor_type_id=existing.anchor_type_id, overridden=True)
        await self._anchors.update_fact(
            existing.id,
            series_uid=series_key(event.series_uid),
            title=stored_title(event.title),
            interval=event.interval,
            location=stored_location(event.location),
            anchor_type_id=assignment.anchor_type_id,
            type_overridden=assignment.overridden,
        )


def _keyed(events: Sequence[RawEvent]) -> Mapping[str, RawEvent]:
    """The incoming events by reconciliation key, last one winning.

    The parser already resolves a duplicate UID within one feed by ``SEQUENCE``, so two events
    reaching one key here means two long UIDs that the digest could not tell apart, which needs a
    SHA-256 collision. Taking the last makes the outcome a function of the parser's order rather
    than of which insert raised on the unique index.
    """
    return {reconciliation_key(event.uid): event for event in events}
