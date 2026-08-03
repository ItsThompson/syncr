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

**An override no occurrence claims is counted, not placed.** A publisher that edits a series' rule
and keeps a previously emitted override produces one, and Google and Exchange exports both do. Every
such override has a master in the same body, so the series it belongs to did expand and its current
rule is what the feed asserts; placing the override as well would put a second event on an occupied
hour, which is what a duplicate master shifting the series' times produces. It is found by comparing
what was registered against what expansion actually consumed, so the answer depends on what the
parser DID rather than on what the partition guessed it would do.

**A tombstone that claims nothing is counted, not silently dropped.** It cancels an occurrence
nobody sent, so there is nothing to suppress, and a count is the only way the arithmetic can see it.
A REPEATED tombstone is counted the same way, for the same reason: a set would absorb it.

``applied`` is the thread through all of this: expansion reports which override keys it consumed, so
one number can mean "replacements that actually replaced something" rather than "replacements that
found a master".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syncr_api.calendars.events import RawEvent
from syncr_api.calendars.ics_errors import UNREPRESENTABLE, MalformedValue
from syncr_api.calendars.ics_recurrence import occurrences
from syncr_api.calendars.ics_times import ONE_DAY, resolve, resolve_day_span, resolve_span
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
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
    cancelled master, a tombstone whose series is absent, a replacement of a series the feed
    cancelled, and an override a tombstone on the same occurrence displaced. Each places nothing,
    and each needs counting or it vanishes from the arithmetic. :func:`parse_feed` adds one more
    form to the reported total, a tombstone no occurrence claimed, so a caller's field holds five.
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
    ``SEQUENCE`` wins, and an equal ``SEQUENCE`` keeps the LIVE one, so the answer does not depend
    on the order a dictionary happens to hold. **Two replacements of the same occurrence resolve by
    ``SEQUENCE`` too**, because an overlapping export repeats an override as readily as it repeats
    a master, but there a cancellation wins outright rather than by revision: see :func:`_resolve`.
    Two CANCELLED replacements of one occurrence say the same thing, so there is nothing to resolve,
    but the second is still counted rather than absorbed.
    """
    masters: dict[str, EventComponent] = {}
    replacements: list[EventComponent] = []
    duplicates = 0
    cancelled = 0
    for candidate in readable:
        if candidate.replaces is not None:
            replacements.append(candidate)
            continue
        held = masters.get(candidate.uid)
        if held is None:
            masters[candidate.uid] = candidate
            continue
        # Two revisions of one series. The higher SEQUENCE wins WHETHER OR NOT either is cancelled:
        # reading the cancellation first would let an older live revision beat the cancellation that
        # superseded it, and place a whole series the feed's latest word says does not happen.
        #
        # At EQUAL SEQUENCE the live one wins, rather than whichever was declared first. Most
        # publishers emit no SEQUENCE at all, so a tie is the common case, and letting document
        # order decide made the same three components answer two ways: declare the cancelled
        # duplicate first and a whole live series with its moved hour disappeared, with the
        # accounting closing over the loss. Preferring the live one is the safe direction, because
        # the alternative deletes occupancy the feed also asserts.
        duplicates += 1
        if (candidate.sequence, not candidate.cancelled) > (held.sequence, not held.cancelled):
            masters[candidate.uid] = candidate

    live = {uid: master for uid, master in masters.items() if not master.cancelled}
    cancelled_uids = masters.keys() - live.keys()
    cancelled += len(cancelled_uids)

    attached: list[EventComponent] = []
    stray: list[EventComponent] = []
    for replacement in replacements:
        if replacement.uid in live:
            attached.append(replacement)
        elif replacement.uid in cancelled_uids:
            # The series this replaces is cancelled, so there is nothing live to attach it to and
            # nothing it could be an occurrence OF. Placing it would turn a cancellation into
            # occupancy.
            cancelled += 1
        else:
            stray.append(replacement)

    # The same precedence applies whether or not the master is present, so it is resolved once. What
    # differs is what happens to the survivors: a replacement of a live series is read against that
    # series' occurrences, while one of an absent series is placed on its own.
    held_by_a_series = _resolve(attached)
    orphaned = _resolve(stray)
    duplicates += held_by_a_series.duplicates + orphaned.duplicates
    cancelled += held_by_a_series.cancelled + orphaned.cancelled
    # An orphaned tombstone cancels an occurrence nobody sent, so it has nothing to suppress and a
    # count is the only way the arithmetic sees it. One that DID suppress an orphan is already
    # counted by `_resolve`.
    cancelled += len(orphaned.tombstones)

    return Series(
        masters=tuple(live.values()),
        overrides=held_by_a_series.overrides,
        tombstones=frozenset(held_by_a_series.tombstones),
        orphans=tuple(orphaned.overrides.values()),
        duplicates=duplicates,
        cancelled=cancelled,
    )


@dataclass(frozen=True, slots=True)
class _Resolved:
    """Replacements of one group, resolved to at most one per occurrence."""

    overrides: dict[OccurrenceKey, EventComponent]
    tombstones: set[OccurrenceKey]
    duplicates: int
    cancelled: int


def _resolve(replacements: Iterable[EventComponent]) -> _Resolved:
    """One replacement per occurrence, and a count of everything that lost.

    Three rules, and they hold whether or not the series these replace is present, which is why this
    is one function rather than two branches that drifted apart:

    - Two live replacements of one occurrence resolve by ``SEQUENCE``, tie to the first declared,
      and the loser is counted. An overlapping export repeats an override as readily as a master.
    - A repeated cancellation has no ``SEQUENCE`` question, both say the same thing, but the second
      is still counted or a set absorbs it and the arithmetic loses a component.
    - A cancellation beats a replacement of the same occurrence, because the feed's cancellation is
      what it means, and the override it displaces is counted rather than dropped silently.

    That last rule is deliberately NOT the master rule, where a cancellation wins only on a higher
    or equal ``SEQUENCE``. Here it wins outright. Most publishers emit no ``SEQUENCE`` at all, so
    the common case is a tie either way, and on a tie both rules agree: the cancellation holds. They
    part only when a cancelled override carries a LOWER ``SEQUENCE`` than a live one, where this
    keeps the hour clear. Refusing to place an hour the feed cancelled somewhere is the safe
    direction, because the alternative is immovable occupancy the user was told does not happen.
    """
    overrides: dict[OccurrenceKey, EventComponent] = {}
    tombstones: set[OccurrenceKey] = set()
    duplicates = 0
    cancelled = 0
    for replacement in replacements:
        key = replaced_key(replacement)
        if replacement.cancelled:
            if key in tombstones:
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

    for key in tombstones & overrides.keys():
        del overrides[key]
        cancelled += 1
    return _Resolved(
        overrides=overrides, tombstones=tombstones, duplicates=duplicates, cancelled=cancelled
    )


def expand(
    master: EventComponent, series: Series, *, horizon: Interval, profile: ZoneProfile
) -> Placement:
    """Every event one master component produces inside ``horizon``.

    An occurrence the feed cancelled produces nothing: the feed said it does not happen, and placing
    it would blank an hour the user actually has. Both a suppressed occurrence and a replaced one
    report their key as applied, because both are replacements that did their job.

    A replacement is placed at the time the REPLACEMENT states, so it can move an occurrence out of
    the horizon entirely. The occurrence generated it, but the event has to land in the window like
    any other, or a plan for February holds an anchor in August.

    Every event is filtered the same way, replacement or not. The expansion window is widened
    backwards by the series' length so an occurrence running INTO the horizon is found, which also
    finds one ending exactly AT it: the horizon is half-open, so that event occupies none of it and
    was an anchor one instant wide. Filtering only the replacements left the same position answered
    two ways depending on whether a publisher had moved it.
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
        span = interval_of(source, at=source.start.wall if replacement else wall, profile=profile)
        if not span.overlaps(horizon):
            continue
        built.append(
            RawEvent(
                uid=occurrence_uid(master.uid, wall) if recurring else master.uid,
                series_uid=master.uid if recurring else None,
                title=source.title,
                interval=span,
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
    That holds for a RECURRING master; a non-recurring one uses its bare uid, so an orphan of it
    gets an occurrence-shaped identity the master would not have given it.

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


def stranded(
    series: Series,
    applied: frozenset[OccurrenceKey],
    *,
    expanded: frozenset[str],
    horizon: Interval,
    profile: ZoneProfile,
) -> tuple[tuple[EventComponent, ...], int, int]:
    """What became of the replacements no occurrence claimed.

    A replacement is registered by UID and read by occurrence, so one naming a time the master's
    rule never produces is registered and never consulted. Comparing what expansion consumed against
    what was registered is the only way to see that, because the partition cannot know which
    occurrences a rule will produce.

    Two outcomes, and the discriminator is whether the master could have covered this hour at all.

    A replacement whose ORIGINAL time falls outside its master's expansion window was never offered
    to that master: the series did not decline it, the window simply did not reach it. It is handed
    back to be placed, exactly as an orphan is, because it may be an hour the user is busy that
    nothing else reports. Dropping it hides an occurrence a publisher moved forward into the window,
    and the plan books over it.

    A replacement whose original time WAS inside the window and still went unclaimed is superseded:
    the rule that would have produced it has changed, or a duplicate master shifted the series'
    times and this override belonged to the losing revision. Placing it as well puts two events on
    one occupied hour, so it is counted.

    ``expanded`` is why the premise is "a master that expanded" rather than "a master in the body".
    A master whose own values were refused places nothing, so nothing in the feed covers the hour
    its replacement names, which is the orphan rule's premise exactly. Reading presence instead made
    the answer depend on WHICH LAYER refused the master: a master with an unreadable zone never
    reaches the partition, so its replacement was sorted as an orphan and placed, while a master
    with an unexpandable rule does reach it, so its replacement was counted and the hour vanished.
    Same feed shape, two answers, decided by which property the publisher got wrong.

    **Whether the replacement's own span reaches the horizon is deliberately not decided here.**
    This function runs outside the boundary that turns a component's values into a rejection, so
    building a span here would put an overflow from a publisher's magnitude outside every catch in
    the package. The placement path already answers it, under that boundary, and counts a
    replacement that lands nowhere as read-and-placed-nothing: the same term this would have added
    it to.
    """
    by_uid = {master.uid: master for master in series.masters if master.uid in expanded}
    reachable: list[EventComponent] = []
    superseded = 0
    for key, replacement in series.overrides.items():
        if key in applied:
            continue
        owner = by_uid.get(replacement.uid)
        if _never_offered(replacement, owner, horizon=horizon, profile=profile):
            reachable.append(replacement)
            continue
        superseded += 1
    return tuple(reachable), superseded, len(series.tombstones - applied)


def _never_offered(
    replacement: EventComponent,
    master: EventComponent | None,
    *,
    horizon: Interval,
    profile: ZoneProfile,
) -> bool:
    """Whether this master's expansion could not have reached the occurrence at all.

    The window is this replacement's OWN master's, looked up by UID. One window for the whole feed
    would be some other master's, and a longer or shorter one changes the answer: the same three
    components then say two different things depending on the order they are declared in, which is
    the harm the duplicate-master tie-break exists to prevent.

    No master means none expanded to cover this hour, whether the master was absent or refused, so
    the answer is the orphan rule's: nothing declined it.

    A magnitude that cannot be resolved is treated as never offered, which hands the component to
    the placement path. That path reports it as a rejection naming the component and the line, where
    raising here would leave the package's no-raise contract to a caller.
    """
    if master is None or replacement.replaces is None:
        return True
    window = _window(horizon, master)
    try:
        original = resolve(replacement.replaces, profile)
    except UNREPRESENTABLE:
        return True
    return not (window.start <= original < window.end)


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
