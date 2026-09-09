"""Placing what each component produces inside the horizon.

The partition (:mod:`syncr_api.calendars.ics_partition`) sorts components by role; this module's
one job is what each surviving one produces. An orphaned override is placed; an unclaimed override
is counted; every event is filtered the same way, replacement or not.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.calendars.events import RawEvent
from syncr_api.calendars.ics_partition import OccurrenceKey, Series, _compete
from syncr_api.calendars.ics_recurrence import occurrences
from syncr_api.calendars.ics_times import ONE_DAY, resolve, resolve_day_span, resolve_span
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from syncr_api.calendars.ics_components import EventComponent
    from syncr_domain.zones import ZoneProfile

_OCCURRENCE_STAMP = "%Y%m%dT%H%M%S"


@dataclass(frozen=True, slots=True)
class Placement:
    """What one component placed, and which replacement keys placing it consumed.

    ``cross_form_duplicates``, ``cross_form_cancelled``, and ``resolved_away`` carry what
    cross-form precedence discarded while deciding which spelling of an occurrence stands.
    """

    events: tuple[RawEvent, ...] = ()
    applied: frozenset[OccurrenceKey] = frozenset()
    cross_form_duplicates: int = 0
    cross_form_cancelled: int = 0
    resolved_away: frozenset[OccurrenceKey] = frozenset()


@dataclass(frozen=True, slots=True)
class _Settled:
    """What settling one master's cross-form groups produced."""

    effective: Series
    cross_form_duplicates: int
    cross_form_cancelled: int
    resolved_away: frozenset[OccurrenceKey]


def _across_forms(
    series: Series, master: EventComponent, produced: Iterable[datetime], *, profile: ZoneProfile
) -> _Settled:
    """Settle replacements of ONE occurrence that a body named in more than one legal form.

    RFC 5545 permits a ``RECURRENCE-ID`` as the occurrence's own wall, UTC, or any named zone,
    so one edit can arrive twice. Sorting resolves each spelling against its own key, which answers
    wrongly. **The produced walls make the competition safe:** two DISTINCT occurrences can share
    an instant, so keys sharing one cannot simply be merged. What discriminates is how many of THIS
    series' own walls resolve onto the instant: one names THE occurrence; two or more are answered
    at match time by :func:`_named_by`.
    """
    if not series.same_instant:
        return _Settled(series, 0, 0, frozenset())
    instants = [resolve(master.start, profile, wall=wall) for wall in produced]
    hosted = Counter(instants)
    overrides = dict(series.overrides)
    tombstones = dict(series.tombstones)
    duplicates = 0
    cancelled = 0
    resolved_away: set[OccurrenceKey] = set()
    for (uid, instant), keys in series.same_instant.items():
        if uid != master.uid or hosted[instant] != 1:
            continue
        # Re-key onto the occurrence's own wall: the survivor is held against the key matching hits.
        own_wall = next(wall for wall, at in zip(produced, instants, strict=True) if at == instant)
        own_key = (uid, own_wall)
        lives, tombs, group_duplicates, group_cancelled = _compete(
            (
                own_key,
                held if (held := overrides.get(key)) is not None else tombstones[key],
            )
            for key in keys
        )
        duplicates += group_duplicates
        cancelled += group_cancelled
        for key in keys:
            resolved_away.add(key)
        resolved_away.discard(own_key)
        for key, component in {**lives, **tombs}.items():
            if component.cancelled:
                tombstones[key] = component
            else:
                overrides[key] = component
    if not resolved_away:
        return _Settled(
            series,
            cross_form_duplicates=duplicates,
            cross_form_cancelled=cancelled,
            resolved_away=frozenset(),
        )
    return _Settled(
        replace(
            series,
            overrides={key: item for key, item in overrides.items() if key not in resolved_away},
            tombstones={key: item for key, item in tombstones.items() if key not in resolved_away},
            same_instant={
                at: tuple(key for key in keys if key not in resolved_away)
                for at, keys in series.same_instant.items()
                if any(key not in resolved_away for key in keys)
            },
        ),
        cross_form_duplicates=duplicates,
        cross_form_cancelled=cancelled,
        resolved_away=frozenset(resolved_away),
    )


def expand(
    master: EventComponent, series: Series, *, horizon: Interval, profile: ZoneProfile
) -> Placement:
    """Every event one master component produces inside ``horizon``.

    An occurrence the feed cancelled produces nothing. A replacement is placed at the time the
    REPLACEMENT states, so it can move an occurrence out of the horizon entirely. Every event is
    filtered the same way: the window is widened backwards so an occurrence running INTO the
    horizon is found.
    """
    window = _window(horizon, master)
    recurring = master.recurrence.recurring
    built: list[RawEvent] = []
    applied: set[OccurrenceKey] = set()
    produced = tuple(occurrences(master.start, master.recurrence, window=window, profile=profile))
    walls = frozenset(produced)
    settled = _across_forms(series, master, produced, profile=profile)
    effective = settled.effective
    for wall in produced:
        key = _named_by(effective, master, wall, applied=applied, walls=walls, profile=profile)
        if key in effective.tombstones:
            applied.add(key)
            continue
        replacement = effective.overrides.get(key)
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
    return Placement(
        events=tuple(built),
        applied=frozenset(applied),
        cross_form_duplicates=settled.cross_form_duplicates,
        cross_form_cancelled=settled.cross_form_cancelled,
        resolved_away=settled.resolved_away,
    )


def _named_by(
    series: Series,
    master: EventComponent,
    wall: datetime,
    *,
    applied: set[OccurrenceKey],
    walls: frozenset[datetime],
    profile: ZoneProfile,
) -> OccurrenceKey:
    """The replacement key this occurrence answers to, in the publisher's spelling or the other one.

    A ``RECURRENCE-ID`` matching this occurrence's own wall time is the ordinary case. A miss falls
    back to the keys sharing the instant this occurrence lands on. **A cross-form match is refused
    when the replacement's own wall is one this series produces:** two occurrences can share an
    instant (a spring-forward gap, or Samoa skipping 30 December 2011). What settles it is the
    produced walls, which do not depend on expansion order.
    """
    exact = (master.uid, wall)
    if exact in series.overrides or exact in series.tombstones:
        return exact
    if not series.same_instant:
        return exact
    instant = resolve(master.start, profile, wall=wall)
    for other in series.same_instant.get((master.uid, instant), ()):
        if other not in applied and other[1] not in walls:
            return other
    return exact


def place_replacement(
    replacement: EventComponent, *, horizon: Interval, profile: ZoneProfile
) -> Placement:
    """The one event an ORPHANED replacement stands for, if it lands in the horizon.

    Placed rather than dropped, because no master in the body covers this commitment. Its identity
    is built from the wall time its own ``RECURRENCE-ID`` states, so a later sync carrying the
    master reconciles to the same anchor. A UTC-form ``RECURRENCE-ID`` on a zoned series states a
    different wall time, so identity does not converge with the master's. See :func:`stranded` for
    a replacement whose master IS present.
    """
    span = interval_of(replacement, at=replacement.start.wall, profile=profile)
    if not span.overlaps(horizon):
        return Placement()
    return Placement(
        events=(
            RawEvent(
                uid=occurrence_uid(replacement.uid, replacement.replaces.wall)
                if replacement.replaces is not None
                else replacement.uid,
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

    A replacement naming a time the master's rule never produces is registered and never consulted.
    One whose ORIGINAL time falls outside its master's window was never offered: it is handed back
    to be placed. One whose original time WAS inside the window and still went unclaimed is
    superseded: placing it as well puts two events on one occupied hour.
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
    return tuple(reachable), superseded, len(series.tombstones.keys() - applied)


def _never_offered(
    replacement: EventComponent,
    master: EventComponent | None,
    *,
    horizon: Interval,
    profile: ZoneProfile,
) -> bool:
    """Whether this master's expansion could not have reached the occurrence at all.

    The window is this replacement's OWN master's. No master means none covered this hour.
    """
    if master is None or replacement.replaces_at is None:
        return True
    window = _window(horizon, master)
    return not (window.start <= replacement.replaces_at < window.end)


def occurrence_uid(uid: str, wall: datetime) -> str:
    """The identity of one occurrence of a series.

    The ORIGINAL wall time distinguishes occurrences, which is what a ``RECURRENCE-ID`` names.
    """
    return f"{uid}#{wall.strftime(_OCCURRENCE_STAMP)}"


def interval_of(source: EventComponent, *, at: datetime, profile: ZoneProfile) -> Interval:
    """The span one occurrence occupies, taken from whichever component defined it."""
    if source.all_day:
        return resolve_day_span(source.start, profile, wall=at, days=source.whole_days)
    return resolve_span(source.start, profile, wall=at, span=source.absolute_span)


def _window(horizon: Interval, master: EventComponent) -> Interval:
    """``horizon`` widened backwards by the event's own length."""
    lead = ONE_DAY * master.whole_days if master.all_day else master.absolute_span
    return Interval(horizon.start - lead, horizon.end)
