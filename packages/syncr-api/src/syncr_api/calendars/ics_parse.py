"""Turning a whole feed into events, and stating why each rejected component produced none.

Four of the ICS ingest table's rows are decided at this level, because each is about how two
components relate rather than about what one says.

**A duplicate ``UID`` within one feed resolves to the later ``SEQUENCE``.** Exports that
concatenate two windows of the same calendar produce this, and taking the first would keep a
superseded revision. The discard is counted, because a feed producing them is worth looking at.

**A ``RECURRENCE-ID`` override replaces exactly the occurrence it names.** The override's own
time, title, and location win, and the occurrence keeps the identity the series gave it, so a
Tuesday that moved appears once rather than twice.

**A cancelled component produces nothing, and WHICH nothing depends on its role.** A cancelled
master cancels the event. A cancelled override cancels one occurrence of a series that is
otherwise live, which is how Exchange and most CalDAV servers express a deleted occurrence, and it
becomes a tombstone rather than a discarded component. Reading cancellation before the role makes
the second look like the absence of an override, so the master's own occurrence is emitted and an
hour the user actually has is blanked.

**No component's events are ever silently dropped.** A component whose expansion would overrun
the per-feed bound is refused whole, with a reason, rather than having the total truncated: a
truncation bounds neither the memory nor the time it took to build, and it discards occupancy with
nothing counting the loss.

The panel's arithmetic therefore closes over every component: kept, rejected, discarded as a
duplicate, discarded as a cancelled master, or applied as an override or a tombstone.

A rejection never fails the fetch. A feed that half-works must read as neither fully working
nor fully broken, so every rejection is collected and everything that parsed is returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from syncr_api.calendars.config import MAX_EVENTS_PER_FEED
from syncr_api.calendars.events import FetchOutcome, RawEvent, RejectedComponent
from syncr_api.calendars.ics_components import EventComponent, read_component
from syncr_api.calendars.ics_errors import (
    UNREPRESENTABLE,
    IcsRejection,
    MalformedValue,
    UnparseableRecurrence,
    as_rejection,
)
from syncr_api.calendars.ics_lines import VEVENT, events_in, parse_components
from syncr_api.calendars.ics_recurrence import occurrences
from syncr_api.calendars.ics_times import ONE_DAY, resolve_day_span, resolve_span
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from datetime import datetime

    from syncr_api.calendars.config import RejectionKind
    from syncr_api.calendars.ics_lines import Component
    from syncr_domain.zones import ZoneProfile

# Everything a component's own values can produce that belongs on the panel rather than in a
# traceback. One tuple, used at all three boundaries below, so "the adapter never raises" is a
# property of this module rather than a promise each `except` clause remembers.
_REPORTABLE = (IcsRejection, *UNREPRESENTABLE)

# The line a feed-level rejection reports when the lexer gave up before naming one.
_UNKNOWN_LINE = 0

# An override is found by the series it belongs to and the occurrence it replaces.
type _OccurrenceKey = tuple[str, datetime]


@dataclass(frozen=True, slots=True)
class _Series:
    """A feed's components sorted by the role each plays, and the discards that sorting produced.

    ``tombstones`` is why this is a struct rather than a tuple of four things. A cancelled
    component is one of two entirely different statements depending on whether it carries a
    ``RECURRENCE-ID``, and conflating them is how a cancelled occurrence ends up in the plan.

    ``orphans`` are overrides whose series is not in this body. That happens for a real reason: an
    export window beginning after a series did emits the moved occurrence and not the master. They
    are kept apart from ``masters`` because their identity is derived differently.
    """

    masters: tuple[EventComponent, ...] = ()
    overrides: Mapping[_OccurrenceKey, EventComponent] = field(default_factory=dict)
    tombstones: frozenset[_OccurrenceKey] = frozenset()
    orphans: tuple[EventComponent, ...] = ()
    duplicates: int = 0
    cancelled_masters: int = 0
    overrides_applied: int = 0


def parse_feed(body: str, *, horizon: Interval, profile: ZoneProfile) -> FetchOutcome:
    """Every event ``body`` declares inside ``horizon``, plus the rejections it produced.

    Two passes, because an override may be declared before the series it belongs to. The first
    reads every component and reports what will not parse at all; the second expands what
    survived, with every override and every tombstone in hand.
    """
    try:
        components = tuple(events_in(parse_components(body)))
    except _REPORTABLE as error:
        # The lexer refused the body itself, so there is no component to attribute this to and no
        # events to keep. One rejection for the whole feed, at the line it gave up on.
        return FetchOutcome(reparsed=True, rejected=(_feed_rejection(as_rejection(error)),))

    rejected: list[RejectedComponent] = []
    readable: list[EventComponent] = []
    for component in components:
        try:
            readable.append(read_component(component, profile))
        except _REPORTABLE as error:
            rejected.append(_rejection(component, as_rejection(error)))

    series = _partition(readable)
    events: list[RawEvent] = []
    remaining = MAX_EVENTS_PER_FEED
    unplaced = 0
    for source, produce in _placements(series, horizon=horizon, profile=profile):
        try:
            produced = produce()
            _require_room_for(produced, remaining=remaining)
        except _REPORTABLE as error:
            rejected.append(_rejection(source.component, as_rejection(error), uid=source.uid))
            continue
        if not produced:
            unplaced += 1
        events.extend(produced)
        remaining -= len(produced)

    return FetchOutcome(
        reparsed=True,
        events=tuple(events),
        rejected=tuple(rejected),
        events_read=len(components),
        duplicates_discarded=series.duplicates,
        cancelled_discarded=series.cancelled_masters,
        overrides_applied=series.overrides_applied,
        unplaced=unplaced,
    )


def _placements(
    series: _Series, *, horizon: Interval, profile: ZoneProfile
) -> Iterator[tuple[EventComponent, Callable[[], list[RawEvent]]]]:
    """Each component that can place events, paired with the call that places them.

    Masters and orphans differ only in how their events are built, so pairing each with its own
    builder lets one loop own the parts that are the same for both: the per-feed bound, the
    rejection, and the count of components that placed nothing.
    """
    for master in series.masters:
        yield master, partial(_expand, master, series, horizon=horizon, profile=profile)
    for orphan in series.orphans:
        yield orphan, partial(_orphan_events, orphan, horizon=horizon, profile=profile)


def _require_room_for(produced: list[RawEvent], *, remaining: int) -> None:
    """Refuse a component whose events would overrun the per-feed bound.

    Refused whole rather than truncated. Slicing the total afterwards bounded neither the memory
    nor the time it took to build, and it discarded occupancy with nothing counting the loss: the
    panel would report a source as healthy while some of the user's commitments had silently
    vanished. A refusal names the component instead, and keeps the counts closing.
    """
    if len(produced) <= remaining:
        return
    message = (
        f"this component expands to {len(produced)} events and only {remaining} of the "
        f"{MAX_EVENTS_PER_FEED} syncr reads per feed are left, so none of it was read"
    )
    raise UnparseableRecurrence(message)


def _partition(readable: list[EventComponent]) -> _Series:
    """Sort a feed's components into masters, overrides, tombstones, orphans, and discards.

    **Cancellation is read after the role, not before it**, and the difference is the whole point.
    A cancelled MASTER cancels the event: it produces nothing and is counted. A cancelled
    OVERRIDE cancels one OCCURRENCE of a series whose master is still live, which is how Exchange
    and most CalDAV servers express a deleted occurrence; it becomes a tombstone that suppresses
    that occurrence. Filtering cancellations first makes the second look like the absence of an
    override, so the master's own occurrence is emitted and the feed's cancelled hour stays in the
    plan as hard occupancy.

    **An override whose series is absent is an orphan, not a no-op.** An export window beginning
    after a series did emits the moved occurrence and not the master, so this is a real publisher's
    behavior rather than a broken feed. A live orphan is placed on its own: the feed asserts the
    commitment, and dropping it would lose an hour the user is actually busy. An orphaned tombstone
    cancels an occurrence of a series nobody sent, so there is nothing to suppress and it is counted
    as a cancellation.

    **An applied override is counted, and not counted twice.** ``overrides_applied`` covers the
    live ones and the tombstones that found their master. Neither is kept as an event of its own
    nor discarded, so without its own term every override would read as a component that vanished.

    Two components with one UID and no ``RECURRENCE-ID`` are the duplicate case. The higher
    ``SEQUENCE`` wins, and a tie keeps the one declared first, so the answer does not depend on
    the order a dictionary happens to hold.
    """
    masters: dict[str, EventComponent] = {}
    replacements: list[EventComponent] = []
    duplicates = 0
    cancelled_masters = 0
    for candidate in readable:
        if candidate.replaces is not None:
            replacements.append(candidate)
            continue
        if candidate.cancelled:
            cancelled_masters += 1
            continue
        held = masters.get(candidate.uid)
        if held is None:
            masters[candidate.uid] = candidate
            continue
        duplicates += 1
        if candidate.sequence > held.sequence:
            masters[candidate.uid] = candidate

    overrides: dict[_OccurrenceKey, EventComponent] = {}
    tombstones: set[_OccurrenceKey] = set()
    orphans: list[EventComponent] = []
    applied = 0
    for replacement in replacements:
        if replacement.uid not in masters:
            if replacement.cancelled:
                cancelled_masters += 1
            else:
                orphans.append(replacement)
            continue
        applied += 1
        key = _replaced_key(replacement)
        if replacement.cancelled:
            tombstones.add(key)
        else:
            overrides[key] = replacement

    return _Series(
        masters=tuple(masters.values()),
        overrides=overrides,
        tombstones=frozenset(tombstones),
        orphans=tuple(orphans),
        duplicates=duplicates,
        cancelled_masters=cancelled_masters,
        overrides_applied=applied,
    )


def _replaced_key(replacement: EventComponent) -> _OccurrenceKey:
    if replacement.replaces is None:  # pragma: no cover - only replacements reach here
        message = "a component with no RECURRENCE-ID was sorted as a replacement"
        raise MalformedValue(message)
    return (replacement.uid, replacement.replaces.wall)


def _orphan_events(
    orphan: EventComponent, *, horizon: Interval, profile: ZoneProfile
) -> list[RawEvent]:
    """The one event an override with no series in this body stands for, if it lands in the horizon.

    Placed rather than dropped, because the feed asserts the commitment and an hour the user is
    busy is the wrong thing to lose. Its identity is the occurrence identity the series would have
    given it, so a later sync that does carry the master reconciles to the same anchor rather than
    creating a second one.
    """
    interval = _interval(orphan, at=orphan.start.wall, profile=profile)
    if not interval.overlaps(horizon):
        return []
    return [
        RawEvent(
            uid=_occurrence_uid(orphan.uid, _replaced_key(orphan)[1]),
            series_uid=orphan.uid,
            title=orphan.title,
            interval=interval,
            location=orphan.location,
            sequence=orphan.sequence,
            all_day=orphan.all_day,
            transparent=orphan.transparent,
        )
    ]


def _expand(
    master: EventComponent, series: _Series, *, horizon: Interval, profile: ZoneProfile
) -> list[RawEvent]:
    """Every event one master component produces inside ``horizon``.

    An occurrence the feed cancelled produces nothing: the feed said it does not happen, and
    placing it would blank an hour the user actually has.
    """
    window = _window(horizon, master)
    recurring = master.recurrence.recurring
    built: list[RawEvent] = []
    for wall in occurrences(master.start, master.recurrence, window=window, profile=profile):
        key = (master.uid, wall)
        if key in series.tombstones:
            continue
        source = series.overrides.get(key, master)
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
                transparent=source.transparent,
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


def _feed_rejection(error: IcsRejection) -> RejectedComponent:
    """The rejection a body the lexer refused renders as.

    The line comes off the error rather than off a component, because the lexer gave up before any
    component closed and there is nothing to attribute it to.
    """
    kind: RejectionKind = error.kind
    return RejectedComponent(
        kind=kind,
        line=error.line or _UNKNOWN_LINE,
        component="VCALENDAR",
        detail=str(error),
    )
