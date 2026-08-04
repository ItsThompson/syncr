"""Preferences, resolved down the override chain and out to instants for one week.

Two resolutions happen here and neither is repeated anywhere else.

**The chain.** An override replaces its Area's declaration WHOLLY rather than field by field, so
what reaches a solve input is one preference out of a chain rather than two merged.
:func:`syncr_domain.preferences.preference_in_effect` is that rule and it is called rather than
restated. A habit or task that declares nothing carries its Area's preference under its OWN
owner, so the solver walks no chain and performs no lookup: what it holds per content is already
the answer.

An Area's preference applies to its own habits and tasks. It does NOT resolve up the Area
ancestry, so a preference on ``Fitness`` is not seen by ``Fitness / Running`` or by anything
inside it. That is what the domain rule states and ticket 1212 carries the question of whether it
should walk.

**The windows.** A declared window is wall time, so ``05:30-07:00`` becomes one interval per date
of the week, each resolved against the zone active on that date. A window naming a stretch that a
spring-forward gap moves is moved with it, because
:func:`syncr_domain.zones.to_instant` resolves both bounds the same way.

A window sits inside one local day: a declaration whose end is at or before its start is refused
where it is authored, so nothing here resolves a wrapping window across two dates. Ticket 1211
carries the question of whether a night-owl window should be expressible.

**A daily cap is an Area's and it does not travel here.** It reaches the solver on the Area
budget, which is what structurally prevents an override relaxing a hard cap: there is no field on
a resolved preference that could carry one. :func:`area_caps` is where the Area-owned figure is
read out, beside the resolution that must not carry it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.intervals import Interval
from syncr_domain.preferences import (
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
    windows = _WeekWindows(zone_by_date)
    resolved: list[ResolvedPreference] = []
    for area in areas:
        owner = PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=area.id)
        resolved.extend(_of(owner, by_owner.get(owner), windows))
    for habit in habits:
        owner = PreferenceOwner(kind=PreferenceOwnerKind.HABIT, id=habit.id)
        resolved.extend(_of(owner, _in_effect(by_owner, owner, habit.area_id), windows))
    for task in tasks:
        owner = PreferenceOwner(kind=PreferenceOwnerKind.TASK, id=task.binding.entity_id)
        resolved.extend(_of(owner, _in_effect(by_owner, owner, task.area_id), windows))
    return tuple(resolved)


def _in_effect(
    by_owner: Mapping[PreferenceOwner, Preference], owner: PreferenceOwner, area_id: AreaId
) -> Preference | None:
    """The override's own preference, or its Area's, or none. Never the two merged."""
    area_owner = PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=area_id)
    return preference_in_effect(by_owner.get(owner), by_owner.get(area_owner))


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
        """Each declared window on each date of the week, in date then declaration order."""
        declared = tuple(windows)
        found = self._resolved.get(declared)
        if found is None:
            found = tuple(self._on(window, on) for on in self._dates for window in declared)
            self._resolved[declared] = found
        return found

    def _on(self, window: LocalTimeWindow, on: Date) -> Interval:
        zone = self._zone_by_date[on]
        return Interval(
            to_instant(window.start, on, zone),
            to_instant(window.end, on, zone),
        )
