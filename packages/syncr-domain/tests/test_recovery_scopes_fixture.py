"""The ``recovery_scopes`` fixture: one window, two declarations, and what each does to a figure.

The fixture's whole content is an asymmetry, so this suite asserts the asymmetry rather than the
literals alone: the absolute declaration leaves the discretionary denominator and the scoped one
stays in it, from the same span at the same anchor time. Every instant is re-derived from the wall
time the docstring states.

The subtraction table is read through ``ForbiddenWindow.occupancy_kind`` rather than restated, so
this fixture and the denominator cannot come to disagree about which kind a window is.
"""

from __future__ import annotations

from datetime import date, time

from syncr_domain.discretionary import OccupancyKind, discretionary_time, is_subtracted
from syncr_domain.fixtures import recovery_scopes
from syncr_domain.gaps import ForbiddenScope
from syncr_domain.intervals import Instant, Interval, IntervalSet
from syncr_domain.weeks import week_span
from syncr_domain.zones import ZoneProfile, to_instant

LONDON = "Europe/London"
PROFILE = ZoneProfile(LONDON)
EMPTY = IntervalSet()


def instant(on: date, at: time) -> Instant:
    return to_instant(at, on, LONDON)


def test_the_span_is_the_week_the_fixture_names() -> None:
    assert week_span(recovery_scopes.WEEK, PROFILE) == recovery_scopes.SPAN


def test_the_commitment_and_its_recovery_are_the_wall_times_the_docstring_states() -> None:
    assert (
        Interval(instant(date(2026, 2, 11), time(16, 0)), instant(date(2026, 2, 11), time(16, 45)))
        == recovery_scopes.COMMITMENT
    )
    assert (
        Interval(instant(date(2026, 2, 11), time(16, 45)), instant(date(2026, 2, 11), time(18, 0)))
        == recovery_scopes.RECOVERY
    )
    assert recovery_scopes.RECOVERY.total_minutes() == recovery_scopes.RECOVERY_MINUTES


def test_the_recovery_begins_exactly_where_the_commitment_ends() -> None:
    # Half-open bounds, so the two abut without overlapping: a window that started a minute early
    # would make every figure taken over both a minute short.
    assert recovery_scopes.COMMITMENT.end == recovery_scopes.RECOVERY.start


def test_the_two_declarations_differ_in_scope_and_in_nothing_else() -> None:
    # The fixture is only usable for a scope comparison if the scope is the only difference.
    assert (
        recovery_scopes.FORBIDDING_EVERY_AREA.interval == recovery_scopes.FORBIDDING_STUDY.interval
    )
    assert recovery_scopes.FORBIDDING_EVERY_AREA.kind == recovery_scopes.FORBIDDING_STUDY.kind
    assert recovery_scopes.FORBIDDING_EVERY_AREA.scope is ForbiddenScope.ALL
    assert recovery_scopes.FORBIDDING_STUDY.scope is ForbiddenScope.AREAS


def test_the_absolute_declaration_forbids_every_area_including_one_declared_later() -> None:
    for area in (recovery_scopes.STUDY, recovery_scopes.FITNESS, recovery_scopes.ADMIN):
        assert recovery_scopes.FORBIDDING_EVERY_AREA.forbids(area)


def test_the_scoped_declaration_forbids_the_one_area_it_names_and_no_other() -> None:
    assert recovery_scopes.FORBIDDING_STUDY.forbids(recovery_scopes.STUDY)
    assert not recovery_scopes.FORBIDDING_STUDY.forbids(recovery_scopes.FITNESS)
    assert not recovery_scopes.FORBIDDING_STUDY.forbids(recovery_scopes.ADMIN)


def test_the_probes_reading_of_the_scoped_form_names_the_same_area() -> None:
    assert recovery_scopes.SCOPED.interval == recovery_scopes.FORBIDDING_STUDY.interval
    assert recovery_scopes.SCOPED.forbids(recovery_scopes.STUDY)
    assert not recovery_scopes.SCOPED.forbids(recovery_scopes.FITNESS)


def test_only_the_absolute_declaration_leaves_the_denominator() -> None:
    # The subtraction table's own answer, read rather than restated: recovery scoped to every Area
    # can be claimed by nobody, and recovery scoped to some Areas is capacity for the rest.
    assert recovery_scopes.FORBIDDING_EVERY_AREA.occupancy_kind is OccupancyKind.RECOVERY_ALL
    assert recovery_scopes.FORBIDDING_STUDY.occupancy_kind is OccupancyKind.RECOVERY_AREAS
    assert is_subtracted(OccupancyKind.RECOVERY_ALL)
    assert not is_subtracted(OccupancyKind.RECOVERY_AREAS)


def test_the_denominator_falls_by_the_window_only_when_it_forbids_everybody() -> None:
    # The figure the asymmetry is about, worked over the fixture's own week: 168 hours, less the
    # 75 minutes when the window forbids every Area, and unchanged when it forbids one.
    absolute = discretionary_time(
        recovery_scopes.SPAN,
        frame=EMPTY,
        anchors=EMPTY,
        absolute_forbidden=IntervalSet([recovery_scopes.RECOVERY]),
        off_plan=EMPTY,
    )
    scoped = discretionary_time(
        recovery_scopes.SPAN, frame=EMPTY, anchors=EMPTY, absolute_forbidden=EMPTY, off_plan=EMPTY
    )

    assert scoped == 168 * 60
    assert absolute == 168 * 60 - recovery_scopes.RECOVERY_MINUTES
