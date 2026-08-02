"""The two daylight-saving weeks: a spring-forward week and a fall-back week.

Both are real: ``Europe/London``, 2026-W13 and 2026-W43, whose transitions fall on
Sunday 2026-03-29 and Sunday 2026-10-25. Interval, zone, grid, and projector tests
all read them, so a DST claim in any layer is made against one set of dates.

Every instant here is a **literal**, deliberately. Deriving the span from
:func:`syncr_domain.weeks.week_span` would make a test asserting ``week_span``
against this fixture a restatement of the code under test rather than a check on it.

Each week carries three spans that exercise a different edge:

*The week span* is 167 or 169 hours, which is what makes a transition week's
discretionary time differ from its neighbour's with no special case anywhere.

*The local transition day* is 23 or 25 hours, which is what the grid's axis must
stay proportional across.

*The Sunday-night frame span* is ``Sleep 23:00 + 8h`` on the last night of the week,
so it starts inside the week and ends inside the next one. The occurrence belongs to
the week its start falls in, unclipped, and is never duplicated into the following
week, so this is the span that proves the boundary rule rather than assuming it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import ZoneProfile

if TYPE_CHECKING:
    from syncr_domain.zones import Date, LocalTime, ZoneId

LONDON: ZoneId = "Europe/London"


@dataclass(frozen=True)
class DstWeek:
    """One week holding a daylight-saving transition, with its asserted figures."""

    label: str
    profile: ZoneProfile
    iso_week: IsoWeek
    transition_date: Date
    span: Interval
    span_minutes: int
    local_transition_day: Interval
    local_transition_day_minutes: int
    sunday_night_frame: Interval
    frame_target_time: LocalTime
    frame_duration_minutes: int

    @property
    def zone(self) -> ZoneId:
        return self.profile.home_zone


SLEEP_TARGET_TIME: LocalTime = time(23, 0)
SLEEP_DURATION_MINUTES = 8 * 60

SPRING_FORWARD = DstWeek(
    label="spring_forward",
    profile=ZoneProfile(LONDON),
    iso_week=IsoWeek(2026, 13),
    # 01:00 GMT jumps to 02:00 BST, so the week and the day each lose an hour.
    transition_date=date(2026, 3, 29),
    span=Interval(
        datetime(2026, 3, 23, 0, 0, tzinfo=UTC),
        datetime(2026, 3, 29, 23, 0, tzinfo=UTC),
    ),
    span_minutes=167 * 60,
    local_transition_day=Interval(
        datetime(2026, 3, 29, 0, 0, tzinfo=UTC),
        datetime(2026, 3, 29, 23, 0, tzinfo=UTC),
    ),
    local_transition_day_minutes=23 * 60,
    sunday_night_frame=Interval(
        datetime(2026, 3, 29, 22, 0, tzinfo=UTC),
        datetime(2026, 3, 30, 6, 0, tzinfo=UTC),
    ),
    frame_target_time=SLEEP_TARGET_TIME,
    frame_duration_minutes=SLEEP_DURATION_MINUTES,
)

FALL_BACK = DstWeek(
    label="fall_back",
    profile=ZoneProfile(LONDON),
    iso_week=IsoWeek(2026, 43),
    # 02:00 BST repeats as 01:00 GMT, so the week and the day each gain an hour.
    transition_date=date(2026, 10, 25),
    span=Interval(
        datetime(2026, 10, 18, 23, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
    ),
    span_minutes=169 * 60,
    local_transition_day=Interval(
        datetime(2026, 10, 24, 23, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
    ),
    local_transition_day_minutes=25 * 60,
    sunday_night_frame=Interval(
        datetime(2026, 10, 25, 23, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 7, 0, tzinfo=UTC),
    ),
    frame_target_time=SLEEP_TARGET_TIME,
    frame_duration_minutes=SLEEP_DURATION_MINUTES,
)

DST_WEEKS = (SPRING_FORWARD, FALL_BACK)
