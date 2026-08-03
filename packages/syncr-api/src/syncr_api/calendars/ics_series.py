"""Sorting a feed's components by the role each plays, and placing what each one produces.

Reading a feed and deciding what its components MEAN to each other are two jobs, and this is the
second. Four rules live here, and each exists because the alternative loses an hour of the user's
time or invents one.

**A cancelled master cancels its whole series, overrides included.** A replacement whose series the
feed cancelled has nothing live to attach to, so it places nothing. Deciding that by dictionary
membership instead would place it as a standalone event: a component the feed said does not happen
becoming hard occupancy, which is the inverse of the harm the cancellation rules exist to prevent.

**An override whose series is absent is an orphan, and it is placed.** An export window beginning
after a series did emits the moved occurrence and not the master, so this is a real publisher's
behavior rather than a broken feed. The feed asserts the commitment; dropping it loses an hour the
user is busy.

**An override no occurrence claims is placed the same way.** A publisher that edits a series' rule
and keeps a previously emitted override produces one, and Google and Exchange exports both do. It is
found by comparing what was registered against what expansion actually consumed, so the answer
depends on what the parser DID rather than on what the partition guessed it would do.

**A tombstone that claims nothing is counted, not silently dropped.** It cancels an occurrence
nobody sent, so there is nothing to suppress, and a count is the only way the arithmetic can see it.

``applied`` is the thread through all of this: expansion reports which override keys it consumed, so
one number can mean "replacements that actually replaced something" rather than "replacements that
found a master".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syncr_api.calendars.events import RawEvent
from syncr_api.calendars.ics_errors import MalformedValue
from syncr_api.calendars.ics_recurrence import occurrences
from syncr_api.calendars.ics_times import ONE_DAY, resolve_day_span, resolve_span
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from syncr_api.calendars.ics_components import EventComponent
    from syncr_domain.zones import ZoneProfile

# A replacement is found by the series it belongs to and the occurrence it replaces.
type OccurrenceKey = tuple[str, datetime]

_OCCURRENCE_STAMP = "%Y%m%dT%H%M%S"


@dataclass(frozen=True, slots=True)
class Series:
    """A feed's components sorted by role, and the discards that sorting produced.

    ``tombstones`` is why this is a struct rather than a tuple of six things. A cancelled component
    is one of two entirely different statements depending on whether it carries a ``RECURRENCE-ID``,
    and conflating them is how a cancelled occurrence ends up in the plan.

    ``cancelled`` counts every component a cancellation discarded, whichever form it took: a
    cancelled master, a tombstone whose series is absent, and a replacement of a series the feed
    cancelled. All three place nothing, and all three need counting or they vanish from the
    arithmetic.
    """

    masters: tuple[EventComponent, ...] = ()
    overrides: Mapping[OccurrenceKey, EventComponent] = field(default_factory=dict)
    tombstones: frozenset[OccurrenceKey] = frozenset()
    orphans: tuple[EventComponent, ...] = ()
    duplicates: int = 0
    cancelled: int = 0


@dataclass(frozen=True, slots=True)
class Placement:
    """What one component placed, and which replacement keys placing it consumed.

    ``applied`` is what lets a replacement's fate be decided by expansion rather than by the
    partition: a key nothing consumed named an occurrence the rule never produces.
    """

    events: tuple[RawEvent, ...] = ()
    applied: frozenset[OccurrenceKey] = frozenset()


def sort_components(readable: list[EventComponent]) -> Series:
    """Sort a feed's components into masters, replacements, orphans, and discards.

    **Cancellation is read after the role, not before it.** A cancelled MASTER cancels the event; a
    cancelled REPLACEMENT cancels one occurrence of a series that is otherwise live, which is how
    Exchange and most CalDAV servers express a deleted occurrence. Filtering cancellations first
    makes the second look like the absence of a replacement, so the master's own occurrence is
    emitted and the feed's cancelled hour stays in the plan as hard occupancy.

    Two components with one UID and no ``RECURRENCE-ID`` are the duplicate case. The higher
    ``SEQUENCE`` wins, and a tie keeps the one declared first, so the answer does not depend on the
    order a dictionary happens to hold. **Two replacements of the same occurrence resolve the same
    way**, because an overlapping export repeats an override as readily as it repeats a master.
    """
    masters: dict[str, EventComponent] = {}
    cancelled_uids: set[str] = set()
    replacements: list[EventComponent] = []
    duplicates = 0
    cancelled = 0
    for candidate in readable:
        if candidate.replaces is not None:
            replacements.append(candidate)
            continue
        if candidate.cancelled:
            cancelled += 1
            cancelled_uids.add(candidate.uid)
            continue
        held = masters.get(candidate.uid)
        if held is None:
            masters[candidate.uid] = candidate
            continue
        duplicates += 1
        if candidate.sequence > held.sequence:
            masters[candidate.uid] = candidate

    overrides: dict[OccurrenceKey, EventComponent] = {}
    tombstones: set[OccurrenceKey] = set()
    orphans: list[EventComponent] = []
    for replacement in replacements:
        if replacement.uid not in masters:
            # No live master, so there is no occurrence this could be. A replacement of a series the
            # feed cancelled is counted rather than placed: placing it would turn a cancellation
            # into occupancy. A replacement of a series that is simply absent is an orphan, which
            # the caller places on its own because the feed asserts the commitment.
            if replacement.cancelled or replacement.uid in cancelled_uids:
                cancelled += 1
            else:
                orphans.append(replacement)
            continue
        key = replaced_key(replacement)
        if replacement.cancelled:
            if key in tombstones:
                # A repeated cancellation of one occurrence. There is no SEQUENCE question to settle
                # (both say the same thing), but the second component still has to be counted or it
                # vanishes from the arithmetic exactly as a repeated override would.
                duplicates += 1
                continue
            tombstones.add(key)
            continue
        held = overrides.get(key)
        if held is None:
            overrides[key] = replacement
            continue
        duplicates += 1
        if replacement.sequence > held.sequence:
            overrides[key] = replacement

    # A feed that both moves an occurrence and cancels it has said it does not happen. The
    # cancellation is read before the replacement, as everywhere else here, and the override it
    # displaces is counted so the component is not lost silently.
    for key in tombstones & overrides.keys():
        del overrides[key]
        cancelled += 1

    return Series(
        masters=tuple(masters.values()),
        overrides=overrides,
        tombstones=frozenset(tombstones),
        orphans=tuple(orphans),
        duplicates=duplicates,
        cancelled=cancelled,
    )


def expand(
    master: EventComponent, series: Series, *, horizon: Interval, profile: ZoneProfile
) -> Placement:
    """Every event one master component produces inside ``horizon``.

    An occurrence the feed cancelled produces nothing: the feed said it does not happen, and placing
    it would blank an hour the user actually has. Both a suppressed occurrence and a replaced one
    report their key as applied, because both are replacements that did their job.
    """
    window = _window(horizon, master)
    recurring = master.recurrence.recurring
    built: list[RawEvent] = []
    applied: set[OccurrenceKey] = set()
    for wall in occurrences(master.start, master.recurrence, window=window, profile=profile):
        key = (master.uid, wall)
        if key in series.tombstones:
            applied.add(key)
            continue
        replacement = series.overrides.get(key)
        if replacement is not None:
            applied.add(key)
        source = replacement or master
        built.append(
            RawEvent(
                uid=occurrence_uid(master.uid, wall) if recurring else master.uid,
                series_uid=master.uid if recurring else None,
                title=source.title,
                interval=interval_of(
                    source, at=source.start.wall if replacement else wall, profile=profile
                ),
                location=source.location,
                sequence=source.sequence,
                all_day=source.all_day,
                transparent=source.transparent,
            )
        )
    return Placement(events=tuple(built), applied=frozenset(applied))


def place_replacement(
    replacement: EventComponent, *, horizon: Interval, profile: ZoneProfile
) -> Placement:
    """The one event an ORPHANED replacement stands for, if it lands in the horizon.

    Placed rather than dropped, because no master in the body covers this commitment and the feed
    asserts it. Its identity is the occurrence identity the series would have given it, so a later
    sync that does carry the master reconciles to the same anchor rather than creating a second one.

    A replacement whose master IS present is not placed here: see :func:`stranded`.
    """
    span = interval_of(replacement, at=replacement.start.wall, profile=profile)
    if not span.overlaps(horizon):
        return Placement()
    return Placement(
        events=(
            RawEvent(
                uid=occurrence_uid(replacement.uid, replaced_key(replacement)[1]),
                series_uid=replacement.uid,
                title=replacement.title,
                interval=span,
                location=replacement.location,
                sequence=replacement.sequence,
                all_day=replacement.all_day,
                transparent=replacement.transparent,
            ),
        )
    )


def stranded(series: Series, applied: frozenset[OccurrenceKey]) -> tuple[int, int]:
    """How many replacements no occurrence claimed: superseded live ones, and tombstones.

    A replacement is registered by UID and read by occurrence, so one naming a time the master's
    rule never produces is registered and never consulted. Comparing what expansion consumed against
    what was registered is the only way to see that, because the partition cannot know which
    occurrences a rule will produce.

    Both are COUNTED rather than placed. Every replacement here has a master in the same body, by
    construction: one without a master was sorted as an orphan. So the series that owns it did
    expand, and its current rule is what the feed asserts. Placing the replacement as well puts two
    events on one occurrence, which is what a duplicate master shifting the series' times produces:
    the losing revision's override outlives the revision it belonged to and doubles the hour. An
    orphan is different and is still placed, because there no master covers the commitment at all.
    """
    superseded = len([key for key in series.overrides if key not in applied])
    return superseded, len(series.tombstones - applied)


def replaced_key(replacement: EventComponent) -> OccurrenceKey:
    """The occurrence a replacement names."""
    if replacement.replaces is None:  # pragma: no cover - only replacements reach here
        message = "a component with no RECURRENCE-ID was sorted as a replacement"
        raise MalformedValue(message)
    return (replacement.uid, replacement.replaces.wall)


def occurrence_uid(uid: str, wall: datetime) -> str:
    """The identity of one occurrence of a series.

    A series expands into many events sharing one UID, and reconciliation is keyed on the UID, so
    each occurrence needs its own or the second would overwrite the first. The ORIGINAL wall time is
    what distinguishes them, which is also what a ``RECURRENCE-ID`` names, so a replacement that
    moves an occurrence keeps that occurrence's identity rather than becoming a second event.
    """
    return f"{uid}#{wall.strftime(_OCCURRENCE_STAMP)}"


def interval_of(source: EventComponent, *, at: datetime, profile: ZoneProfile) -> Interval:
    """The span one occurrence occupies, taken from whichever component defined it."""
    if source.all_day:
        return resolve_day_span(source.start, profile, wall=at, days=source.whole_days)
    return resolve_span(source.start, profile, wall=at, span=source.absolute_span)


def _window(horizon: Interval, master: EventComponent) -> Interval:
    """``horizon`` widened backwards by the event's own length.

    An occurrence that began before the horizon and runs into it is still occupancy the solver has
    to respect, so the lower bound has to reach back far enough to find it.
    """
    lead = ONE_DAY * master.whole_days if master.all_day else master.absolute_span
    return Interval(horizon.start - lead, horizon.end)
