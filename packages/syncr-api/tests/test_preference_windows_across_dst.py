"""What a declared preferred window does on a daylight-saving transition date.

Its own suite, because the mechanism is one and the answers are five: a date whose resolved bounds
do not run forward is dropped, and every other date keeps a window at whatever its own arithmetic
makes it, which can be the declared length, shorter, or longer.

Every figure here was measured through the real ``assemble`` against the repository's own
``dst_weeks`` fixture rather than derived from the rule, because the rule is what got this wrong
once: the round-1 delivery reasoned that no reachable case existed and shipped that reasoning as a
claim, and both halves of the counter-example were already written down in the tree.

```
declared        spring-forward 2026-03-29              fall-back 2026-10-25
01:00-01:30     30m, shifted to 02:00 local            30m
00:45-02:15     30m, NARROWED                          150m, WIDENED
01:45-02:00     dropped: the bounds invert             75m
01:00-02:00     dropped: the bounds collapse           120m
05:30-07:00     90m                                    90m
```
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

from syncr_domain.fixtures.dst_weeks import FALL_BACK, SPRING_FORWARD
from tests.assembly_fakes import (
    NOW,
    FakeAreas,
    FakePreferences,
    FakeSettings,
    a_preference,
    a_window,
    an_area,
    an_area_owner,
    an_assembler,
)

if TYPE_CHECKING:
    from syncr_domain.fixtures.dst_weeks import DstWeek
    from syncr_solver.inputs import ResolvedPreference

DECLARED_MINUTES = 90


async def resolved(week: DstWeek, start: time, end: time) -> ResolvedPreference:
    """One Area preference of one window, resolved for ``week`` through the real assembler."""
    fitness = an_area(name="Fitness")
    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        settings=FakeSettings(week.zone),
        preferences=FakePreferences(
            [a_preference(owner=an_area_owner(fitness.id), windows=[a_window(start, end)])]
        ),
    ).assemble(week.iso_week, NOW)
    return inputs.preferences[0]


def on_the_transition(week: DstWeek, preference: ResolvedPreference) -> list[int]:
    """The minutes of each window that falls on the week's transition date, in the local zone."""
    zone = ZoneInfo(week.zone)
    return [
        window.total_minutes()
        for window in preference.windows
        if window.start.astimezone(zone).date() == week.transition_date
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [(time(1, 0), time(2, 0)), (time(1, 30), time(2, 30)), (time(1, 45), time(2, 0))],
    ids=["collapses", "collapses at the gap's far side", "inverts"],
)
async def test_a_window_whose_resolved_bounds_do_not_run_forward_drops_that_date(
    start: time, end: time
) -> None:
    # Both bounds resolve through one mapping that is NOT order-preserving across the gap: on
    # Europe/London 2026-03-29 both 01:30 and 02:30 are 01:30Z, so a window declared forward in wall
    # time collapses or inverts in instants. Every one of these raised from `Interval` before the
    # guard, which failed the whole assembly: every solve, pin, live verdict and background assembly
    # for that week, annually, on a declaration the boundary accepts.
    preference = await resolved(SPRING_FORWARD, start, end)

    assert len(preference.windows) == 6
    assert on_the_transition(SPRING_FORWARD, preference) == []


async def test_a_window_clear_of_the_gap_keeps_every_date_at_the_declared_length() -> None:
    # The control for the guard above: it drops a date, not a week, and not a length.
    preference = await resolved(SPRING_FORWARD, time(5, 30), time(7, 0))

    assert len(preference.windows) == 7
    assert on_the_transition(SPRING_FORWARD, preference) == [DECLARED_MINUTES]


async def test_a_window_wholly_inside_the_gap_is_shifted_rather_than_dropped() -> None:
    # The rule is about the bounds running forward, not about the hour existing: a window inside the
    # gap has both bounds shifted by the gap, so it stays 30 minutes and lands an hour later. Pinned
    # because the docstring used to claim such a date carried no window, which is broader than the
    # guard and was false.
    preference = await resolved(SPRING_FORWARD, time(1, 0), time(1, 30))
    zone = ZoneInfo(SPRING_FORWARD.zone)

    assert len(preference.windows) == 7
    assert on_the_transition(SPRING_FORWARD, preference) == [30]
    shifted = next(
        window
        for window in preference.windows
        if window.start.astimezone(zone).date() == SPRING_FORWARD.transition_date
    )
    assert shifted.start.astimezone(zone).strftime("%H:%M") == "02:00"


async def test_a_window_spanning_the_gap_is_narrowed_by_the_hour_the_day_lost() -> None:
    # The half the fix pass left unstated, and the more surprising of the two: a 90-minute preferred
    # window is 30 minutes on this date, which can leave it too small for the session it was
    # declared for. Same arithmetic as the widening below, with the sign flipped.
    preference = await resolved(SPRING_FORWARD, time(0, 45), time(2, 15))

    assert len(preference.windows) == 7
    assert on_the_transition(SPRING_FORWARD, preference) == [30]


async def test_a_window_spanning_the_repeat_is_widened_by_the_hour_the_day_gained() -> None:
    preference = await resolved(FALL_BACK, time(0, 45), time(2, 15))

    assert len(preference.windows) == 7
    assert on_the_transition(FALL_BACK, preference) == [150]


async def test_a_fall_back_date_carries_the_wider_window_the_repeated_hour_makes() -> None:
    # `fold=0` takes the earlier offset for the ambiguous start while the end sits after the repeat,
    # so an hour declared across the repeat is two hours on this date and no other.
    preference = await resolved(FALL_BACK, time(1, 0), time(2, 0))

    assert len(preference.windows) == 7
    assert on_the_transition(FALL_BACK, preference) == [120]
    assert sorted({window.total_minutes() for window in preference.windows}) == [60, 120]


async def test_the_shortest_window_the_repeat_swallows_grows_by_the_whole_hour() -> None:
    # Fifteen declared minutes become 75 on this date, which is the same mechanism at its extreme
    # and the figure a reader is least likely to predict. It is also the mirror of the inverting
    # case above: the same declaration drops the spring date and stretches the fall-back one.
    preference = await resolved(FALL_BACK, time(1, 45), time(2, 0))

    assert len(preference.windows) == 7
    assert on_the_transition(FALL_BACK, preference) == [75]
