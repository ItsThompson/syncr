"""A preferred stretch authored across midnight, resolved onto the two dates it covers.

Its own suite, because the seam is one declaration becoming two stored windows and then one
resolved interval spanning two dates, and every figure below is a pair of dates rather than a
count of minutes: a resolution that lost the pre-midnight half and kept the other reads as a
plausible one-hour window on the wrong night, and a total-minutes assertion passes over it.

``23:00`` to ``01:00`` is stored as the two windows ``00:00-01:00`` and ``23:00-00:00``, and the
second closes on the FOLLOWING date. So each date's pre-midnight half abuts the next date's
post-midnight half, the two merge, and the week carries one 120-minute interval per night plus a
60-minute remainder at each end of the week, where the other half of the night belongs to the week
either side.

Every figure here was measured through the real ``assemble``, and both daylight-saving directions
apply to the merged interval rather than to either half:

```
declared    spring-forward night into 2026-03-29    fall-back night into 2026-10-25
23:00-01:00 120m, the far bound READING 02:00        120m
            local because 01:00 does not exist
23:00-02:00 120m, NARROWED by the hour the day       240m, WIDENED by the repeated hour
            lost
```
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from syncr_api.learned.weight_reading import as_weight_set
from syncr_domain.fixtures.dst_weeks import FALL_BACK, LONDON, SPRING_FORWARD
from syncr_domain.identity import BindingRef
from syncr_domain.preferences import authored_windows
from syncr_domain.weeks import IsoWeek
from syncr_solver.preferred import MISFIT_SOFT, ResolvedPreferences, misfit_of
from tests.assembly_fakes import (
    NOW,
    WEEK,
    FakeAreas,
    FakeHabits,
    FakePreferences,
    FakeSettings,
    FakeTasks,
    a_habit,
    a_preference,
    a_task,
    a_weight_set,
    a_window,
    an_area,
    an_area_owner,
    an_assembler,
    between,
)

if TYPE_CHECKING:
    from syncr_domain.zones import Date, ZoneId
    from syncr_solver.inputs import ResolvedPreference

WRAP_START = time(23, 0)
WRAP_END = time(1, 0)

IDEAL_SESSION_MINUTES = 90

# No fitted curve for any Area, so the misfit a placement carries is the declared component alone.
WEIGHTS = as_weight_set(a_weight_set())

# The only zone shape under which a wrap's POST-midnight half can fail to run forward: Cuba moves
# 00:00 to 01:00 on the second Sunday of March, so on that date the half's own two bounds, 00:00 and
# 01:00, both resolve to the one instant the clock reaches when it jumps.
MIDNIGHT_GAP_ZONE: ZoneId = "America/Havana"
MIDNIGHT_GAP_WEEK = IsoWeek(2025, 10)


async def resolved(
    *, iso_week: IsoWeek, zone: ZoneId, start: time, end: time
) -> ResolvedPreference:
    """One Area preference of one authored stretch, resolved through the real assembler.

    The stretch is split by the domain's own authoring rule rather than by a hand-built pair, so
    what this resolves is the shape storage actually holds.
    """
    fitness = an_area(name="Fitness")
    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        settings=FakeSettings(zone),
        preferences=FakePreferences(
            [
                a_preference(
                    owner=an_area_owner(fitness.id),
                    windows=authored_windows(start=start, end=end),
                )
            ]
        ),
    ).assemble(iso_week, NOW)
    return inputs.preferences[0]


def local_spans(preference: ResolvedPreference, zone: ZoneId) -> list[tuple[str, str, int]]:
    """Each resolved window as its two wall-clock ends, dates included, and its minutes.

    Both ends carry their own date because that is the reading under test: an interval opening at
    23:00 and closing at 01:00 says nothing about which night it covers until its dates are read,
    and the minutes are beside them because a daylight-saving date can hold two dates and one hour.
    """
    here = ZoneInfo(zone)
    return [
        (
            window.start.astimezone(here).strftime("%Y-%m-%d %H:%M"),
            window.end.astimezone(here).strftime("%Y-%m-%d %H:%M"),
            window.total_minutes(),
        )
        for window in preference.windows
    ]


async def test_a_wrap_covers_the_night_from_each_date_into_the_next() -> None:
    # The whole week, stated rather than counted: the pre-midnight half of each date closes on the
    # next date, so Monday's declaration covers Monday 23:00 to Tuesday 01:00. Resolving both
    # bounds against the declaration's own date instead loses every pre-midnight half to the
    # forward-running guard and leaves seven one-hour windows, each on the night BEFORE the one the
    # user asked for.
    preference = await resolved(iso_week=WEEK, zone=LONDON, start=WRAP_START, end=WRAP_END)

    assert local_spans(preference, LONDON) == [
        ("2026-02-09 00:00", "2026-02-09 01:00", 60),
        ("2026-02-09 23:00", "2026-02-10 01:00", 120),
        ("2026-02-10 23:00", "2026-02-11 01:00", 120),
        ("2026-02-11 23:00", "2026-02-12 01:00", 120),
        ("2026-02-12 23:00", "2026-02-13 01:00", 120),
        ("2026-02-13 23:00", "2026-02-14 01:00", 120),
        ("2026-02-14 23:00", "2026-02-15 01:00", 120),
        ("2026-02-15 23:00", "2026-02-16 00:00", 60),
    ]


async def test_a_stretch_that_ends_at_midnight_and_does_not_wrap_closes_on_the_next_date() -> None:
    # The closing rule is about an end of 00:00, not about wrap-ness: one window ending at the day's
    # end is one interval per date, and it runs to the following midnight rather than to its own.
    preference = await resolved(iso_week=WEEK, zone=LONDON, start=time(22, 0), end=time(0, 0))

    assert local_spans(preference, LONDON) == [
        (f"2026-02-{9 + day:02d} 22:00", f"2026-02-{10 + day:02d} 00:00", 120) for day in range(7)
    ]


async def test_the_merged_wrap_holds_a_ninety_minute_session_neither_half_could() -> None:
    # What the merge is for. The solver charges misfit unless a window holds the WHOLE placement, so
    # two abutting sixty-minute halves refuse a ninety-minute session that the two hours they cover
    # between them fit exactly.
    preference = await resolved(iso_week=WEEK, zone=LONDON, start=WRAP_START, end=WRAP_END)
    across_midnight = between(23.5, 25)
    at_breakfast = between(8, 9.5)
    solver_view = ResolvedPreferences([preference])
    binding = BindingRef.for_habit(uuid4(), index=0)

    assert across_midnight.total_minutes() == IDEAL_SESSION_MINUTES
    assert at_breakfast.total_minutes() == IDEAL_SESSION_MINUTES
    assert (
        misfit_of(
            across_midnight,
            binding=binding,
            area_id=preference.owner.id,
            hour=23,
            preferences=solver_view,
            weights=WEIGHTS,
        )
        == 0.0
    )
    assert (
        misfit_of(
            at_breakfast,
            binding=binding,
            area_id=preference.owner.id,
            hour=8,
            preferences=solver_view,
            weights=WEIGHTS,
        )
        == MISFIT_SOFT
    )


@pytest.mark.parametrize(
    ("end", "spring_forward_minutes", "fall_back_minutes"),
    [(time(1, 0), 120, 120), (time(2, 0), 120, 240)],
    ids=["ending where the transition begins", "ending past the transition"],
)
async def test_a_wrap_carries_the_transition_on_the_night_that_holds_it(
    end: time, spring_forward_minutes: int, fall_back_minutes: int
) -> None:
    # The mechanism the module docstring tabulates, applied to a merged interval: the night running
    # into the transition date is narrower or wider than the declaration by the hour that date lost
    # or gained, and a wrap whose far bound is the transition's own hour keeps its length in both
    # directions. Every other night of both weeks is the declared length.
    spring_forward = await resolved(
        iso_week=SPRING_FORWARD.iso_week, zone=LONDON, start=WRAP_START, end=end
    )
    fall_back = await resolved(iso_week=FALL_BACK.iso_week, zone=LONDON, start=WRAP_START, end=end)

    assert nights_into(spring_forward, SPRING_FORWARD.transition_date) == [spring_forward_minutes]
    assert nights_into(fall_back, FALL_BACK.transition_date) == [fall_back_minutes]


def nights_into(preference: ResolvedPreference, on: Date) -> list[int]:
    """The minutes of each resolved window that CLOSES on ``on``, in the London zone.

    Closes rather than opens, because a wrap's own night is named by the date it ends on: the
    daylight-saving transition sits after midnight, so the interval that carries it opened the
    previous day.
    """
    here = ZoneInfo(LONDON)
    return [
        window.total_minutes()
        for window in preference.windows
        if window.end.astimezone(here).date() == on
    ]


async def test_a_half_whose_bounds_collapse_is_absent_for_its_own_date_alone() -> None:
    # The forward-running guard applies per half, so a date losing its post-midnight half keeps its
    # pre-midnight one and every other date keeps the whole wrap. On 2025-03-09 Cuba's clock jumps
    # from 00:00 to 01:00, so the 00:00-01:00 half resolves to one instant and is dropped: the night
    # into that date is the sixty minutes its pre-midnight half covers, and it closes at 01:00 local
    # because the bound at midnight shifted with the gap.
    preference = await resolved(
        iso_week=MIDNIGHT_GAP_WEEK, zone=MIDNIGHT_GAP_ZONE, start=WRAP_START, end=WRAP_END
    )

    assert local_spans(preference, MIDNIGHT_GAP_ZONE) == [
        ("2025-03-03 00:00", "2025-03-03 01:00", 60),
        ("2025-03-03 23:00", "2025-03-04 01:00", 120),
        ("2025-03-04 23:00", "2025-03-05 01:00", 120),
        ("2025-03-05 23:00", "2025-03-06 01:00", 120),
        ("2025-03-06 23:00", "2025-03-07 01:00", 120),
        ("2025-03-07 23:00", "2025-03-08 01:00", 120),
        ("2025-03-08 23:00", "2025-03-09 01:00", 60),
        ("2025-03-09 23:00", "2025-03-10 00:00", 60),
    ]


async def test_two_windows_declared_to_abut_reach_the_solver_as_one() -> None:
    # The merge is general rather than wrap-specific, and it has to be: storage records nothing
    # about having been authored as one stretch, so a reader cannot tell the halves of a wrap from
    # two windows the user declared separately. Both cover one run of the day, and one member per
    # covered run is what the solver reads.
    fitness = an_area(name="Fitness")
    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        settings=FakeSettings(LONDON),
        preferences=FakePreferences(
            [
                a_preference(
                    owner=an_area_owner(fitness.id),
                    windows=[
                        a_window(time(6, 0), time(7, 0)),
                        a_window(time(7, 0), time(8, 0)),
                    ],
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    assert local_spans(inputs.preferences[0], LONDON) == [
        (f"2026-02-{9 + day:02d} 06:00", f"2026-02-{9 + day:02d} 08:00", 120) for day in range(7)
    ]


async def test_one_declaration_resolves_once_however_many_owners_carry_it() -> None:
    # An Area's preference is carried by every habit and task in it, and the intervals cannot differ
    # between them, so the three owners hold the one resolution rather than three equal copies. A
    # second, different declaration is resolved separately.
    fitness = an_area(name="Fitness")
    habit = a_habit(area_id=fitness.id)
    task = a_task(area_id=fitness.id)
    reading = an_area(name="Reading")

    inputs = await an_assembler(
        areas=FakeAreas([fitness, reading]),
        habits=FakeHabits([habit]),
        tasks=FakeTasks([task]),
        settings=FakeSettings(LONDON),
        preferences=FakePreferences(
            [
                a_preference(
                    owner=an_area_owner(fitness.id),
                    windows=authored_windows(start=WRAP_START, end=WRAP_END),
                ),
                a_preference(
                    owner=an_area_owner(reading.id), windows=[a_window(time(5, 30), time(7, 0))]
                ),
            ]
        ),
    ).assemble(WEEK, NOW)

    carried = [entry.windows for entry in inputs.preferences if entry.owner.id != reading.id]
    other = next(entry.windows for entry in inputs.preferences if entry.owner.id == reading.id)
    assert len(carried) == 3
    assert all(windows is carried[0] for windows in carried)
    assert other is not carried[0]


def test_the_week_the_wrap_is_measured_on_holds_no_transition() -> None:
    # The control the date-pinned assertions rest on: 2026-W07 is GMT throughout, so every night in
    # it is the declared length and any figure that differs differs for a stated reason. The eighth
    # day is the Monday the last night runs into. Read from the zone rather than from a claim.
    here = ZoneInfo(LONDON)

    offsets = {
        here.utcoffset(datetime.combine(WEEK.monday() + timedelta(days=day), time(12, 0)))
        for day in range(8)
    }

    assert offsets == {timedelta(0)}
