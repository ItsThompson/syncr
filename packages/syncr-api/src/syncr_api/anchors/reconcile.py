"""Reconciliation: turning what a feed just published into the anchors a tenant holds.

Keyed on ``(source_id, external_uid)`` and nothing else. Not on the title and the time, because
a lecture moved by an hour is the same commitment at a new time, and diffing on its content
would read that as one commitment cancelled and another created: every block the first
displaced would be freed and then displaced again, and a plan would churn once per room change.

**Only a successful read removes an anchor.** A feed that could not be read and a feed that
answered "unchanged" both produce an empty event list, so removing on an empty list would clear
every anchor of a healthy feed that had nothing new to say. The caller distinguishes the three
attempts and calls the matching method; this module never has to guess.

**A delta removes only what it names.** A change-bearing delta is a successful read whose events
are reconciled exactly as a full read's are, but its silence means "as you last saw it", not "no
longer published": so ``outcome.incremental`` switches the removal rule from absence (everything
the read does not mention) to identifier (exactly what the provider reported removed). One branch,
and it lives here rather than in a second reconcile method, because everything else -- keying,
typing, override carry-forward, week invalidation, the count read off the rows -- is the same work.

**Typing happens here, not afterwards.** A created anchor is matched against the tenant's rules
in one pass, and an occurrence of a series the user has already retyped inherits that override
instead. Doing it in a second pass would leave a window in which an anchor existed with no type,
and any reader in that window would see opaque busy time where a shadow belongs.

**A series override is read before the removal, and that is the narrow ordering that matters.**
The overrides a tenant holds are read off the occurrences carrying them, so they must be read while
those occurrences still exist. ``remove_absent`` is what destroys them: as the horizon rolls
forward, every old occurrence of a daily standup drops out of the feed and new ones arrive, and
reading before the removal is what carries the override across that turnover. Re-reading mid-loop
would also work; reading after the removal would not.

**A pass that moved occupancy invalidates the weeks it moved it in.** A week's inputs include every
commitment that can cast a product inside it, so creating, moving or removing one changes what a
solve of that week read, and the week input version is the counter such a solve is guarded on. The
read that carries an override forward is what makes a REMOVED anchor's week available too: the
removal answers with a count, so a week not taken off the prior state before the delete cannot be
recovered after it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.anchors.identity import (
    carries_a_dropped_character,
    reconciliation_key,
    series_key,
    stored_location,
    stored_title,
)
from syncr_api.anchors.matching import first_match, series_overrides
from syncr_api.anchors.reach import widest_reach
from syncr_api.calendars.anchor_writing import AnchorDelta
from syncr_api.user_settings.solve_inputs import contiguous_ranges, weeks_occupied
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.anchors.matching import SeriesOverrides
    from syncr_api.anchors.reach import ShadowReach
    from syncr_api.anchors.records import AnchorRecord, AnchorTypeId, AnchorTypeRecord
    from syncr_api.anchors.repository import AnchorRepository
    from syncr_api.anchors.type_repository import AnchorTypeRepository
    from syncr_api.calendars.events import FetchOutcome, RawEvent
    from syncr_api.calendars.records import CalendarSourceId, CalendarSourceRecord
    from syncr_api.user_settings.solve_inputs import WeekInputVersions
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneId

_log = get_logger("syncr.anchors")


@dataclass(frozen=True, slots=True)
class _Assignment:
    """The type one incoming event resolves to, and where that answer came from."""

    anchor_type_id: AnchorTypeId | None
    overridden: bool


class AnchorReconciler:
    """One tenant's anchors, made to agree with what their sources publish."""

    def __init__(
        self,
        anchors: AnchorRepository,
        types: AnchorTypeRepository,
        *,
        versions: WeekInputVersions,
        home_zone: ZoneId,
    ) -> None:
        self._anchors = anchors
        self._types = types
        self._versions = versions
        self._home_zone = home_zone

    @measured("anchors")
    async def reconcile(self, source: CalendarSourceRecord, outcome: FetchOutcome) -> AnchorDelta:
        """Make ``source``'s anchors match what was just read, and report what changed.

        Creates what is new, replaces the fact of what moved or was renamed, and removes what the
        read says is gone. Every anchor it touches stops being possibly stale, because the source
        just confirmed it. The weeks whose occupancy moved are invalidated in this transaction, so
        a solve that read one of them fails its own conditional write.

        What "gone" means follows the reading: a full read states what is present and absence
        removes the rest; a delta states what changed and removes exactly the identifiers the
        provider named. Both counts come back from the rows, never from the events, because two
        entries can reach one reconciliation key.
        """
        held = await self._anchors.list_for_source(source.id)
        by_key = {anchor.external_uid: anchor for anchor in held}
        overrides = series_overrides(held)
        types = await self._types.list_all()
        incoming = _keyed(outcome.events)
        # One reach for the tenant rather than one per anchor, because a week reads every
        # commitment that can cast a product inside it and `casting_span` widens that read by the
        # same two maxima over this same set. Read off the types this tenant holds, so a
        # declaration edited to a 14-hour lead moves this with it.
        reach = widest_reach(one.specification for one in types)

        created = 0
        updated = 0
        scrubbed = 0
        occupied: set[IsoWeek] = set()
        for key, event in incoming.items():
            existing = by_key.get(key)
            assignment = self._assign(source.id, event, types=types, overrides=overrides)
            scrubbed += _lost_a_character(event)
            if existing is None:
                await self._create(source.id, key, event, assignment)
                created += 1
                occupied.update(self._weeks_reached(event.interval, reach))
                continue
            if await self._update(existing, event, assignment):
                updated += 1
                # Both spans, so a commitment moved across a week boundary invalidates the week it
                # left as well as the one it arrived in: the week it left now holds free time that
                # its solve read as occupied.
                occupied.update(self._weeks_reached(existing.interval, reach))
                occupied.update(self._weeks_reached(event.interval, reach))

        # Taken off the prior state, BEFORE any delete: a removal answers with a count, so a removed
        # commitment's occupancy is unreadable once the delete has run.
        if outcome.incremental:
            # A delta's silence is not evidence of removal, so the identifiers it NAMES are the only
            # ones taken off. Keys are matched through the same reconciliation function the stored
            # half went through, or a provider echoing a UID with whitespace in it would name an
            # anchor the table no longer addresses.
            reported = {reconciliation_key(uid) for uid in outcome.removed_uids}
            for key, anchor in by_key.items():
                if key in reported:
                    occupied.update(self._weeks_reached(anchor.interval, reach))
            removed = await self._anchors.remove_reported(source.id, keys=reported)
        else:
            for key, anchor in by_key.items():
                if key not in incoming:
                    occupied.update(self._weeks_reached(anchor.interval, reach))
            removed = await self._anchors.remove_absent(source.id, keeping=set(incoming))
        delta = AnchorDelta(
            created=created,
            updated=updated,
            removed=removed,
            scrubbed=scrubbed,
            current=await self._anchors.count_for_source(source.id),
            occupied_weeks=frozenset(occupied),
        )
        await self._invalidate(delta.occupied_weeks)
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

    def _weeks_reached(self, anchor: Interval, reach: ShadowReach) -> tuple[IsoWeek, ...]:
        """Every ISO week a commitment at ``anchor`` is an input of.

        Its own span widened by ``reach``, which is the envelope every product of it falls inside.
        A week reads the commitments that can cast a product into it rather than only the ones
        inside it, so an exam on Monday morning is an input of the week before it as well: that is
        where its prep lands.
        """
        return weeks_occupied(reach.envelope(anchor), home_zone=self._home_zone)

    async def _invalidate(self, weeks: frozenset[IsoWeek]) -> None:
        """Bump the weeks this pass changed, as ranges closed at both ends.

        **Closed at both ends, and never one range spanning the weeks a feed touches.** A poll runs
        every fifteen minutes, and a bump with no end date invalidates every tracked week from its
        first week onwards: each pass that moved one commitment would then supersede the solve of
        every week the user has not yet lived, each supersession enqueues a follow-up, and the next
        pass supersedes those. The single-flight invariant holds throughout -- one solve per week --
        while no week ever reaches a write, which is a worse failure than a missing bump because it
        looks like work. A range spanning what one pass touched has the same shape in miniature: two
        commitments a term apart would invalidate the weeks between them, which nothing changed.

        The open-ended shape exists and is reserved for a mutation that genuinely has no end date,
        which a poll is not.

        One range per unbroken run rather than one per week, because a published component may
        legitimately be a year long and the weeks it covers are all genuinely its own. The grouping
        widens a range only onto the week that immediately follows it, so the weeks bumped are the
        weeks this pass changed and no others.
        """
        for span in contiguous_ranges(weeks):
            await self._versions.bump(span)

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
    ) -> bool:
        """Replace the fact, and answer whether anything actually moved.

        Keeps the user's override if the anchor already carried one, so a retyped occurrence keeps
        its type when its title changes into something another rule would match. A rule match is
        recomputed, because the title it was derived from may have moved.

        The write is unconditional but the COUNT is not. A steady feed republishes every event on
        every poll, so counting each one as updated would report a number equal to the whole set
        forever and say nothing about what changed. `possibly_stale` is part of the comparison
        because clearing it IS a change: an anchor a failed sync marked stale becomes unstale here.
        """
        if existing.type_overridden:
            assignment = _Assignment(anchor_type_id=existing.anchor_type_id, overridden=True)
        title = stored_title(event.title)
        series = series_key(event.series_uid)
        location = stored_location(event.location)
        moved = (
            existing.title != title
            or existing.series_uid != series
            or existing.interval != event.interval
            or existing.location != location
            or existing.anchor_type_id != assignment.anchor_type_id
            or existing.type_overridden != assignment.overridden
            or existing.possibly_stale
        )
        await self._anchors.update_fact(
            existing.id,
            series_uid=series,
            title=title,
            interval=event.interval,
            location=location,
            anchor_type_id=assignment.anchor_type_id,
            type_overridden=assignment.overridden,
        )
        return moved


def _lost_a_character(event: RawEvent) -> int:
    """1 when any of this event's stored values lost a control character, else 0.

    Per event rather than per value, so a feed whose every component carries one bad byte reports
    the number of commitments affected rather than four times that.
    """
    return int(
        any(
            carries_a_dropped_character(value)
            for value in (event.uid, event.series_uid, event.title, event.location)
        )
    )


def _keyed(events: Sequence[RawEvent]) -> Mapping[str, RawEvent]:
    """The incoming events by reconciliation key, last one winning.

    Two events reach one key for either of two reachable reasons: a SHA-256 collision between two
    oversized UIDs, or two UIDs the SCRUB made equal, which needs no collision at all. The second is
    reachable whenever two UIDs differ only by a control character or only by whitespace, and it
    became reachable when the scrub was added.

    So the resolution here is FEED ORDER, not the parser's ``SEQUENCE`` rule. The parser resolves a
    duplicate UID within one feed by ``SEQUENCE`` before this is reached; it cannot resolve two UIDs
    that were distinct to it and equal here. Last-one-wins is still the right choice, because it
    makes the outcome a function of the parser's ordering rather than of which insert happened to
    raise on the unique index.
    """
    return {reconciliation_key(event.uid): event for event in events}
