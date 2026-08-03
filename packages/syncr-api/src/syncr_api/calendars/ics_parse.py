"""Turning a whole feed into events, and stating why each rejected component produced none.

Three of the ICS ingest table's rows are decided at this level, because each is about how two
components relate rather than about what one says.

**A duplicate ``UID`` within one feed resolves to the later ``SEQUENCE``.** Exports that
concatenate two windows of the same calendar produce this, and taking the first would keep a
superseded revision. The discard is counted, because a feed producing them is worth looking at.

**A ``RECURRENCE-ID`` override replaces exactly the occurrence it names.** The override's own
time, title, and location win, and the occurrence keeps the identity the series gave it, so a
Tuesday that moved appears once rather than twice.

**A cancelled component produces nothing.** ``STATUS:CANCELLED`` is the feed saying the event
does not happen, and treating it as occupancy would blank an hour the user actually has. It is
counted rather than silently dropped, so the panel's arithmetic closes: read, kept, rejected,
duplicated, and cancelled account for every component.

A rejection never fails the fetch. A feed that half-works must read as neither fully working
nor fully broken, so every rejection is collected and everything that parsed is returned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.calendars.config import MAX_EVENTS_PER_FEED
from syncr_api.calendars.events import FetchOutcome, RawEvent, RejectedComponent
from syncr_api.calendars.ics_components import EventComponent, read_component
from syncr_api.calendars.ics_errors import IcsRejection
from syncr_api.calendars.ics_lines import VEVENT, events_in, parse_components
from syncr_api.calendars.ics_recurrence import occurrences
from syncr_api.calendars.ics_times import ONE_DAY, resolve_day_span, resolve_span
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.config import RejectionKind
    from syncr_api.calendars.ics_lines import Component
    from syncr_domain.zones import ZoneProfile

# An override is found by the series it belongs to and the occurrence it replaces.
type _OccurrenceKey = tuple[str, datetime]


def parse_feed(body: str, *, horizon: Interval, profile: ZoneProfile) -> FetchOutcome:
    """Every event ``body`` declares inside ``horizon``, plus the rejections it produced.

    Two passes, because an override may be declared before the series it belongs to. The first
    reads every component and reports what will not parse at all; the second expands what
    survived, with every override in hand.
    """
    components = tuple(events_in(parse_components(body)))
    rejected: list[RejectedComponent] = []
    readable: list[EventComponent] = []
    cancelled = 0

    for component in components:
        try:
            candidate = read_component(component, profile)
        except IcsRejection as error:
            rejected.append(_rejection(component, error))
            continue
        if candidate.cancelled:
            cancelled += 1
        else:
            readable.append(candidate)

    masters, overrides, duplicates = _partition(readable)
    events: list[RawEvent] = []
    for master in masters:
        try:
            events.extend(_expand(master, overrides, horizon=horizon, profile=profile))
        except IcsRejection as error:
            rejected.append(_rejection(master.component, error, uid=master.uid))

    return FetchOutcome(
        events=tuple(events[:MAX_EVENTS_PER_FEED]),
        rejected=tuple(rejected),
        events_read=len(components),
        duplicates_discarded=duplicates,
        cancelled_discarded=cancelled,
    )


def _partition(
    readable: list[EventComponent],
) -> tuple[list[EventComponent], dict[_OccurrenceKey, EventComponent], int]:
    """Masters, overrides keyed by the occurrence each replaces, and the duplicate count.

    Two components with one UID and no ``RECURRENCE-ID`` are the duplicate case. The higher
    ``SEQUENCE`` wins, and a tie keeps the one declared first, so the answer does not depend
    on the order a dictionary happens to hold.
    """
    masters: dict[str, EventComponent] = {}
    overrides: dict[_OccurrenceKey, EventComponent] = {}
    duplicates = 0
    for candidate in readable:
        if candidate.replaces is not None:
            overrides[candidate.uid, candidate.replaces.wall] = candidate
            continue
        held = masters.get(candidate.uid)
        if held is None:
            masters[candidate.uid] = candidate
            continue
        duplicates += 1
        if candidate.sequence > held.sequence:
            masters[candidate.uid] = candidate
    return list(masters.values()), overrides, duplicates


def _expand(
    master: EventComponent,
    overrides: dict[_OccurrenceKey, EventComponent],
    *,
    horizon: Interval,
    profile: ZoneProfile,
) -> list[RawEvent]:
    """Every event one master component produces inside ``horizon``."""
    window = _window(horizon, master)
    recurring = master.recurrence.recurring
    built: list[RawEvent] = []
    for wall in occurrences(master.start, master.recurrence, window=window, profile=profile):
        source = overrides.get((master.uid, wall), master)
        built.append(
            RawEvent(
                uid=_occurrence_uid(master.uid, wall) if recurring else master.uid,
                series_uid=master.uid if recurring else None,
                title=source.title,
                interval=_interval(
                    source, at=source.start.wall if source is not master else wall, profile=profile
                ),
                location=source.location,
                sequence=source.sequence,
                all_day=source.all_day,
            )
        )
    return built


def _interval(source: EventComponent, *, at: datetime, profile: ZoneProfile) -> Interval:
    """The span one occurrence occupies, taken from whichever component defined it."""
    if source.all_day:
        return resolve_day_span(source.start, profile, wall=at, days=source.whole_days)
    return resolve_span(source.start, profile, wall=at, span=source.absolute_span)


def _window(horizon: Interval, master: EventComponent) -> Interval:
    """``horizon`` widened backwards by the event's own length.

    An occurrence that began before the horizon and runs into it is still occupancy the
    solver has to respect, so the lower bound has to reach back far enough to find it.
    """
    lead = ONE_DAY * master.whole_days if master.all_day else master.absolute_span
    return Interval(horizon.start - lead, horizon.end)


def _occurrence_uid(uid: str, wall: datetime) -> str:
    """The identity of one occurrence of a series.

    A series expands into many events sharing one UID, and reconciliation is keyed on the UID,
    so each occurrence needs its own or the second would overwrite the first. The ORIGINAL
    wall time is what distinguishes them, which is also what a ``RECURRENCE-ID`` names, so an
    override that moves an occurrence keeps that occurrence's identity rather than becoming a
    second event.
    """
    return f"{uid}#{wall.strftime('%Y%m%dT%H%M%S')}"


def _rejection(
    component: Component, error: IcsRejection, *, uid: str | None = None
) -> RejectedComponent:
    """The rejection this failure renders as, with the component and the line it began on."""
    kind: RejectionKind = error.kind
    return RejectedComponent(
        kind=kind,
        line=component.line,
        component=component.name or VEVENT,
        detail=str(error),
        uid=uid,
    )
