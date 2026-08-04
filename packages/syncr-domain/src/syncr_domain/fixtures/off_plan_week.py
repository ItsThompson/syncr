"""The ``off_plan_week`` fixture: a Friday-to-Monday span, in a real zone, over a real week.

One week, ``Europe/London`` 2026-W43, and one off-plan span running from Friday 2026-10-23
at 14:00 to Monday 2026-10-26 at 09:00. That span was chosen because it is three boundaries
at once, and each of the three is a place an off-plan defect hides:

*It crosses an ISO week boundary.* Monday 2026-10-26 starts 2026-W44, so the span is ONE
record that two weeks each hold part of. A week's assembly clips it; storage never splits
it.

*It crosses a daylight-saving transition.* The clocks go back on Sunday 2026-10-25, so the
span's elapsed length is 68 hours while a wall-clock subtraction of its two ends gives 67.
Both figures are stated below, and the wrong one is stated so a test can assert against
something rather than against a number with no alternative.

*Its end is a quarter-hour instant inside a Monday, not a midnight.* An off-plan period is
not restricted to whole days or whole weeks, and the fixture would not exercise that if it
began and ended at local midnight.

``keeping_frame`` and ``dropping_frame`` are the same span declared two ways, and they are
alternatives rather than a pair: two periods covering one instant are refused, so a test
uses one or the other. The distinction they carry is the whole of ``keep_frame``. Dropping
the frame is the holiday abroad, where ``Sleep`` and ``Lunch`` stop appearing; keeping it is
the quiet week at home, where the routines stay and nothing else is placed.

Every instant here is a **literal**, deliberately, exactly as in :mod:`.dst_weeks`. Deriving
them from ``to_instant`` would make a test that asserts an off-plan figure against this
fixture a restatement of the code under test. ``tests/test_off_plan_week_fixture.py``
re-derives every one of them from the stated wall times, which is what earns the literals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from syncr_domain.intervals import Interval
from syncr_domain.off_plan import OffPlanPeriod
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import ZoneProfile

if TYPE_CHECKING:
    from syncr_domain.zones import Date, LocalTime, ZoneId

LONDON: ZoneId = "Europe/London"


@dataclass(frozen=True)
class WallInterval:
    """A span as a user authors one: two local dates and two local times, no zone.

    What it names becomes an instant only through a zone, which is why the fixture carries
    both this and the derived interval. The pair is what the fixture's own suite compares.
    """

    start_on: Date
    start_at: LocalTime
    end_on: Date
    end_at: LocalTime


@dataclass(frozen=True)
class WallSpan:
    """A span authored as a local start plus a duration, the way a routine or a pin is."""

    on: Date
    at: LocalTime
    minutes: int


@dataclass(frozen=True)
class OffPlanWeek:
    """One week holding a Friday-to-Monday off-plan span, with its asserted figures."""

    label: str
    profile: ZoneProfile
    iso_week: IsoWeek
    following_week: IsoWeek
    transition_date: Date
    week_span: Interval
    week_span_minutes: int
    off_plan_wall: WallInterval
    off_plan: Interval
    # Elapsed minutes, which is what the denominator subtracts.
    off_plan_minutes: int
    # What subtracting the two wall times would give instead. One hour less, because the
    # clocks go back inside the span. Stated so a test can assert the difference.
    off_plan_wall_minutes: int
    off_plan_minutes_inside_the_week: int
    off_plan_minutes_inside_the_following_week: int
    keeping_frame: OffPlanPeriod
    dropping_frame: OffPlanPeriod
    pin_wall: WallSpan
    pin: Interval
    frame_wall: WallSpan
    frame_inside: Interval
    # The span exactly covering the week, for the week that is entirely off-plan.
    whole_week: Interval
    # Starting exactly where `off_plan` ends: adjacency is not overlap, so both are
    # declarable, and this is the pair that says so.
    abutting_wall: WallInterval
    abutting: Interval

    @property
    def zone(self) -> ZoneId:
        return self.profile.home_zone


# Friday 14:00 BST to Monday 09:00 GMT, over the weekend the clocks go back.
_OFF_PLAN_WALL = WallInterval(
    start_on=date(2026, 10, 23), start_at=time(14, 0), end_on=date(2026, 10, 26), end_at=time(9, 0)
)
_OFF_PLAN = Interval(
    datetime(2026, 10, 23, 13, 0, tzinfo=UTC),
    datetime(2026, 10, 26, 9, 0, tzinfo=UTC),
)

# One pinned block inside the span: "mostly off" needs no off-plan-specific affordance.
_PIN_WALL = WallSpan(on=date(2026, 10, 24), at=time(10, 0), minutes=60)

# The Saturday-night `Sleep` occurrence, wholly inside the off-plan span and itself crossing
# the transition. It is what makes the union load-bearing: summing the subtrahends would
# remove these eight hours twice.
_FRAME_WALL = WallSpan(on=date(2026, 10, 24), at=time(23, 0), minutes=8 * 60)

_ABUTTING_WALL = WallInterval(
    start_on=date(2026, 10, 26), start_at=time(9, 0), end_on=date(2026, 10, 26), end_at=time(17, 0)
)

OFF_PLAN_WEEK = OffPlanWeek(
    label="friday_to_monday",
    profile=ZoneProfile(LONDON),
    iso_week=IsoWeek(2026, 43),
    following_week=IsoWeek(2026, 44),
    transition_date=date(2026, 10, 25),
    # The same 169-hour week `dst_weeks.FALL_BACK` states, repeated as a literal rather than
    # imported: this fixture's suite re-derives it, so a copy that drifted would fail there.
    week_span=Interval(
        datetime(2026, 10, 18, 23, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
    ),
    week_span_minutes=169 * 60,
    off_plan_wall=_OFF_PLAN_WALL,
    off_plan=_OFF_PLAN,
    off_plan_minutes=68 * 60,
    off_plan_wall_minutes=67 * 60,
    # To the end of the week's span, which is Monday's local midnight: 59 hours.
    off_plan_minutes_inside_the_week=59 * 60,
    # And from there to Monday 09:00, which is the following week's first nine hours.
    off_plan_minutes_inside_the_following_week=9 * 60,
    keeping_frame=OffPlanPeriod(interval=_OFF_PLAN, keep_frame=True, label="recovering"),
    dropping_frame=OffPlanPeriod(interval=_OFF_PLAN, keep_frame=False, label="Italy"),
    pin_wall=_PIN_WALL,
    pin=Interval(
        datetime(2026, 10, 24, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 24, 10, 0, tzinfo=UTC),
    ),
    frame_wall=_FRAME_WALL,
    frame_inside=Interval(
        datetime(2026, 10, 24, 22, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 6, 0, tzinfo=UTC),
    ),
    whole_week=Interval(
        datetime(2026, 10, 18, 23, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
    ),
    abutting_wall=_ABUTTING_WALL,
    abutting=Interval(
        datetime(2026, 10, 26, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 17, 0, tzinfo=UTC),
    ),
)
