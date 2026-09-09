"""Preferences, resolved down the override chain and out to instants for one week.

Two resolutions happen here and neither is repeated anywhere else.

**The chain.** An override replaces its Area's declaration WHOLLY rather than field by field, so
what reaches a solve input is one preference out of a chain rather than two merged.
:func:`syncr_domain.preferences.preference_in_effect` is that rule and it is called rather than
restated. A habit or task that declares nothing carries its Area's preference under its OWN
owner, so the solver walks no chain and performs no lookup: what it holds per content is already
the answer.

An Area's preference resolves up the Area ancestry through the same walk the preference route
uses, so a preference on ``Fitness`` reaches ``Fitness / Running`` and everything inside it.

**The windows.** A declared window is wall time, so ``05:30-07:00`` becomes one interval per date
of the week, each resolved against the zone active on that date.

**An end of ``00:00`` is the end of the day, so it resolves onto the FOLLOWING date's midnight.** A
stretch the user authored across midnight is stored as two windows split at the boundary, so the
pre-midnight half covers the night out of the date it was declared for and into the next: a wrap
declared from 23:00 to 01:00 covers Monday 23:00 to Tuesday 01:00. Both bounds resolve against the
zone active on the date the window is read FOR, including the bound that lands on the following
date, because that bound closes this date's own day and the following date can be outside the week.

**Resolved intervals that abut or overlap are merged.** That is what makes the two halves of one
authored stretch reach the solver as the one interval the user declared, and it is a merge rather
than a pairing because storage records nothing about having been authored as one stretch: what a
reader holds is a set of windows, and one member per covered run is the only reading of a set with
no choices left in it. It is also what lets a 90-minute session fit a wrap from 23:00 to 01:00,
since the solver asks whether ONE window holds a whole placement rather than whether several cover
it between them. The merge is general: two windows declared to abut, ``06:00-07:00`` and
``07:00-08:00``, likewise reach the solver as one.

**A window is dropped for a date only when its own resolved bounds do not run forward.** Resolving
both bounds through :func:`syncr_domain.zones.to_instant` is NOT order-preserving across a
spring-forward gap: every wall time inside the gap shifts onto a real time later in the day, so on
``Europe/London``, 2026-03-29, both 01:30 and 02:30 resolve to ``2026-03-29T01:30Z``. A window whose
start falls inside the gap and whose end is at or after the gap's end therefore collapses to one
instant or inverts, and that window is absent for that date, while every other date of the week
keeps its own. The unit dropped is one window on one date rather than the date itself, so a date
losing one half of an authored wrap still carries the other. Shifting the end forward instead would
invent an hour the day does not have, and a preference is a wall-clock window rather than a
duration.

**Every other date keeps a window at whatever its own arithmetic makes it, which is not always the
declared length.** One mechanism, two directions, both measured on the ``dst_weeks`` fixture:

```
declared        spring-forward date 2026-03-29        fall-back date 2026-10-25
01:00-01:30     30m, shifted to 02:00 local           30m
00:45-02:15     30m, NARROWED by the hour the day     150m, WIDENED by the repeated hour
                lost
01:45-02:00     dropped: the bounds invert            75m
01:00-02:00     dropped: the bounds collapse          120m
05:30-07:00     90m                                   90m
23:00-01:00     120m, its far bound READING 02:00     120m
                local because 01:00 does not exist
23:00-02:00     120m, NARROWED                        240m, WIDENED
```

The two wrapping rows are the night CLOSING on the transition date, which opens on the day before
it, and both figures are the merged interval's rather than either half's.

A soft window that is narrower or wider once a year costs nothing, and the narrowing is the more
surprising of the two because it is the one that can leave a window too small for the session it was
declared for. Both are stated here and pinned by tests so neither is read later as a defect.

A stored window runs forward in wall time, and an end of ``00:00`` is the one bound that may read
earlier than the start it belongs to: a declaration whose end is at or before its start in any
other way is refused where it is authored, and one authored across midnight is split into two
windows there rather than stored as a pair of bounds that run backwards. That rule is checked in
WALL TIME, which is why the guard above exists: an invariant verified in one coordinate system does
not survive a non-monotonic mapping into another.

**A daily cap is an Area's and it does not travel here.** It reaches the solver on the Area
budget, which is what structurally prevents an override relaxing a hard cap: there is no field on
a resolved preference that could carry one. :func:`area_caps` is where the Area-owned figure is
read out, beside the resolution that must not carry it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from syncr_api.preferences.owners import area_ancestry
from syncr_common.logging import get_logger
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.preferences import (
    END_OF_DAY,
    PreferenceOwner,
    PreferenceOwnerKind,
    preference_in_effect,
)
from syncr_domain.zones import to_instant
from syncr_solver.inputs import ResolvedPreference

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.areas.records import AreaRecord
    from syncr_api.habits.records import HabitRecord
    from syncr_api.preferences.records import PreferenceRecord
    from syncr_domain.identifiers import AreaId
    from syncr_domain.preferences import LocalTimeWindow, Preference
    from syncr_domain.zones import Date, ZoneId
    from syncr_solver.inputs import EligibleTask

_log = get_logger("syncr.plans")

_ONE_DAY: Final = timedelta(days=1)


def area_caps(stored: Sequence[PreferenceRecord]) -> Mapping[AreaId, int | None]:
    """Each Area's own daily ceiling, from an AREA preference and from nothing else.

    An override cannot carry one, so this reads the Area-owned rows only. An Area with no
    preference, or one whose preference declares no cap, has none.
    """
    return {
        record.owner.id: record.max_per_day_minutes
        for record in stored
        if record.owner.kind is PreferenceOwnerKind.AREA
    }


def resolved_preferences(
    stored: Sequence[PreferenceRecord],
    *,
    areas: Sequence[AreaRecord],
    habits: Sequence[HabitRecord],
    tasks: Sequence[EligibleTask],
    zone_by_date: Mapping[Date, ZoneId],
) -> tuple[ResolvedPreference, ...]:
    """One resolved preference per owner that has one: Areas first, then habits, then tasks.

    An owner whose chain yields nothing is absent rather than present with no windows, because
    "no preference" and "a preference naming no window" are different statements: the second is
    how one habit opts out of a preference the rest of its Area keeps.
    """
    by_owner = {record.owner: record.as_preference() for record in stored}
    areas_by_id = {area.id: area for area in areas}
    windows = _WeekWindows(zone_by_date)
    resolved: list[ResolvedPreference] = []
    for area in areas:
        owner = PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=area.id)
        resolved.extend(_of(owner, _in_effect(by_owner, owner, area.id, areas_by_id), windows))
    for habit in habits:
        owner = PreferenceOwner(kind=PreferenceOwnerKind.HABIT, id=habit.id)
        resolved.extend(
            _of(owner, _in_effect(by_owner, owner, habit.area_id, areas_by_id), windows)
        )
    for task in tasks:
        owner = PreferenceOwner(kind=PreferenceOwnerKind.TASK, id=task.binding.entity_id)
        resolved.extend(_of(owner, _in_effect(by_owner, owner, task.area_id, areas_by_id), windows))
    return tuple(resolved)


def _in_effect(
    by_owner: Mapping[PreferenceOwner, Preference],
    owner: PreferenceOwner,
    area_id: AreaId,
    areas_by_id: Mapping[AreaId, AreaRecord],
) -> Preference | None:
    """The owner's preference, or its nearest Area ancestor's, or none. Never merged."""
    area_links = (
        by_owner.get(PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=area.id))
        for area in area_ancestry(areas_by_id, area_id)
    )
    return preference_in_effect(by_owner.get(owner), *area_links)


def _of(
    owner: PreferenceOwner, preference: Preference | None, windows: _WeekWindows
) -> tuple[ResolvedPreference, ...]:
    """``preference`` under ``owner``, with its windows as instants, or nothing at all."""
    if preference is None:
        return ()
    return (
        ResolvedPreference(
            owner=owner,
            windows=windows.of(preference.windows),
            strength=preference.strength,
            preferred_duration_minutes=preference.preferred_duration_minutes,
        ),
    )


def _closes_on(window: LocalTimeWindow, on: Date) -> Date:
    """The date this window's end bound names: the following one where it is the day's end."""
    if window.end == END_OF_DAY:
        return on + _ONE_DAY
    return on


class _WeekWindows:
    """Declared windows as instants for one week, resolved once per distinct declaration.

    Memoized because a preference declared on an Area is carried by every habit and task in it,
    so an unmemoized resolution would resolve one declaration once per owner for a figure that
    cannot differ between them.
    """

    __slots__ = ("_dates", "_resolved", "_zone_by_date")

    def __init__(self, zone_by_date: Mapping[Date, ZoneId]) -> None:
        self._zone_by_date = zone_by_date
        self._dates = sorted(zone_by_date)
        self._resolved: dict[tuple[LocalTimeWindow, ...], tuple[Interval, ...]] = {}

    def of(self, windows: Sequence[LocalTimeWindow]) -> tuple[Interval, ...]:
        """Each declared window on each date of the week, merged where they meet, earliest first.

        A week can carry fewer intervals than it has dates times declarations, for either of two
        reasons: a date whose own daylight-saving gap leaves a window naming no stretch of time
        contributes nothing, and two resolved intervals that abut or overlap are one.
        """
        declared = tuple(windows)
        found = self._resolved.get(declared)
        if found is None:
            found = IntervalSet(
                interval
                for on in self._dates
                for window in declared
                if (interval := self._on(window, on)) is not None
            ).members
            self._resolved[declared] = found
        return found

    def _on(self, window: LocalTimeWindow, on: Date) -> Interval | None:
        """This window on ``on``, or nothing when its resolved bounds do not run forward.

        A spring-forward gap is not order-preserving, so two bounds a declaration ordered in wall
        time can resolve to one instant, or backwards. That is the ONE case a date is dropped for:
        the alternative is an assembly that raises, and this is the widest integration point in the
        product and the one with no degraded mode.

        A window ending at the day's end closes on the following date, so the two halves of an
        authored wrap are dropped or kept independently: a date whose own half collapses is absent
        for that half while every other date keeps its window.

        A date whose bounds still run forward keeps its window at whatever the day's own arithmetic
        makes it, which can be narrower or wider than the declared length. The module docstring
        tabulates both directions.
        """
        zone = self._zone_by_date[on]
        start = to_instant(window.start, on, zone)
        end = to_instant(window.end, _closes_on(window, on), zone)
        if start >= end:
            _log.info(
                "plans.preference.window_absent_on_this_date",
                on=str(on),
                zone=zone,
                window=str(window),
            )
            return None
        return Interval(start, end)
