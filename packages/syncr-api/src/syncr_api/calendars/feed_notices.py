"""The panel a feed that stopped answering raises, and the days it puts in doubt.

A stale feed is the quietest failure in the ingest path. Its anchors are retained and marked
possibly stale rather than removed, because a failed poll is not evidence that a lecture was
cancelled, so every day it fed renders exactly as it did while the feed was healthy. A degraded
state that looks identical to a working one is what this notice exists to make visible.

**Both halves of the sentence are known here and nowhere else.** Whether a feed is failing is on
the source row; which days it put in doubt is in the anchors it contributed. The threshold is
applied once, here, and the notice names the source and the days it decided about, so a surface
renders what it is given rather than computing staleness for itself.

**A feed that has never succeeded raises on its first failure**, and the age it reports is measured
from when the user added it. There is no last success to be within the threshold of, so waiting
would leave a feed added with a wrong address silent for half a day; and every other instant on the
row moves with each failed poll, so an age measured from one of those would report the same few
minutes of staleness forever.

**The write target is not here.** Its ``last_error`` records a failed projection rather than a
failed read, and that condition already raises a banner and a panel of its own. Two notices for one
condition is how a reader learns to ignore both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from syncr_api.calendars.config import ANCHOR_SOURCE, ERROR, STALE_AFTER
from syncr_api.calendars.day_spans import local_day_start
from syncr_api.core.notices import AMBER, PANEL, Notice, NoticeScope
from syncr_api.google_account.notices import stated_duration
from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date, datetime

    from syncr_api.calendars.records import CalendarSourceId, CalendarSourceRecord
    from syncr_domain.zones import ZoneProfile

# The identity root every stale-feed notice shares. The source's own identifier follows it, so a
# client keys one panel per feed and a second read of an unchanged condition produces the same id.
FEED_STALE: Final = "calendar.feed-stale"

SETTINGS_SCREEN: Final = "settings"

# What survives a feed that cannot be read. Both are unconditionally true, which is the property
# that matters: this module reads the failing feed and its anchors and nothing else, so a sentence
# whose truth depended on the write target's health would be a promise it cannot check. The plan
# reaching the calendar is deliberately NOT claimed here for that reason.
ANCHORS_RETAINED: Final = (
    "The commitments this feed already contributed, which are retained and marked possibly stale"
)
SOLVING_STILL_WORKS: Final = (
    "Solving the week, which still plans around every commitment already read"
)
FEED_STILL_WORKS: Final = (ANCHORS_RETAINED, SOLVING_STILL_WORKS)

# A single day, which is the count the notice words differently from several.
A_SINGLE_DAY = 1

# How the panel opens, per case, so the branch a notice took is nameable rather than inferable from
# the sentence it produced. A feed that has never answered and one that answered days ago are two
# different facts, and stating the wrong one is the panel asserting a read that never happened.
NEVER_ANSWERED: Final = "This feed has never been read successfully, and was added"
LAST_ANSWERED: Final = "It last answered"

# How it names the days, per case, for the same reason: a notice about three days must not word
# itself as a notice about one.
NO_DAY_IN_DOUBT: Final = "It has contributed nothing to the days ahead, so no day is in doubt."
ONE_DAY_HOLDS: Final = "holds commitments it contributed."
SEVERAL_DAYS_HOLD: Final = "hold commitments it contributed."


def is_feed_stale(source: CalendarSourceRecord, *, now: datetime) -> bool:
    """Whether this feed has been failing long enough to be worth telling the user about.

    Read from ``state`` rather than from the three fields under it, because that property already
    decides which conditions can be failing at all: an excluded source reports the user's own
    choice, and a source with no error is not failing. Only ``error`` reaches the threshold.
    """
    if source.role != ANCHOR_SOURCE or source.state != ERROR:
        return False
    succeeded = source.sync_state.last_success_at
    return succeeded is None or now - succeeded > STALE_AFTER


def failing_since(source: CalendarSourceRecord) -> datetime:
    """The instant the outage is measured from: the last success, or when the source was added.

    Never the last attempt, which each failed poll refreshes: an age measured from it would report
    one poll interval of staleness for as long as the feed stayed broken.
    """
    return source.sync_state.last_success_at or source.created_at


def markable_span(*, now: datetime, profile: ZoneProfile, horizon: Interval) -> Interval:
    """Every instant a surface could still mark a day for: local midnight today, to the horizon.

    From midnight rather than from ``now``, because a reader looking at today has already had the
    morning: a span starting at the current instant leaves today off the list while the day plainly
    holds the feed's commitments.

    The earlier of the two starts is taken because the two ends resolve in different zones. The home
    zone decides which date today is and the zone active on that date decides when it began, so a
    travel override can put today's midnight after the horizon ends, and an interval needs its start
    before its end.
    """
    midnight = local_day_start(local_date(now, profile.home_zone), profile)
    return Interval(min(midnight, horizon.start), horizon.end)


def stale_feed_notices(
    sources: Iterable[CalendarSourceRecord],
    days: Mapping[CalendarSourceId, Sequence[date]],
    *,
    now: datetime,
) -> tuple[Notice, ...]:
    """One amber panel per stale feed, in the order the sources were given.

    A source with no entry in ``days`` is one that has contributed nothing to the days ahead, which
    is a notice that names no day rather than no notice: the feed is still failing.
    """
    return tuple(
        _notice(source, tuple(days.get(source.id, ())), now=now)
        for source in sources
        if is_feed_stale(source, now=now)
    )


def _notice(source: CalendarSourceRecord, days: tuple[date, ...], *, now: datetime) -> Notice:
    return Notice(
        id=f"{FEED_STALE}.{source.id}",
        volume=PANEL,
        pigment=AMBER,
        title=f"{source.display_name} could not be read",
        detail=_detail(source, days, now=now),
        unavailable=[f"Reading new commitments from {source.display_name}"],
        still_works=list(FEED_STILL_WORKS),
        since=failing_since(source),
        scope=NoticeScope(
            screen=SETTINGS_SCREEN,
            source_id=str(source.id),
            dates=[day.isoformat() for day in days],
        ),
    )


def _detail(source: CalendarSourceRecord, days: tuple[date, ...], *, now: datetime) -> str:
    """Why it failed, how long it has been failing, and which days hold what it contributed.

    The stored reason already ends with the sentence saying the anchors are retained and marked
    possibly stale, so that is not repeated here: one statement of that fact, written where the
    failure is raised.
    """
    return " ".join(
        part
        for part in (source.sync_state.last_error, _how_long(source, now=now), _affected(days))
        if part
    )


def _how_long(source: CalendarSourceRecord, *, now: datetime) -> str:
    """How long the feed has been failing, as a duration rather than as an instant.

    A duration is what makes a reader act; a timestamp makes them do arithmetic. The instant is on
    the notice as ``since`` for a surface that wants to render it its own way.

    Which of the two openings is used is the load-bearing part: a feed that has never answered must
    not be described as one that answered a while ago, because the duration reads identically either
    way and only the opening says which happened.
    """
    for_how_long = stated_duration(now - failing_since(source))
    if source.sync_state.last_success_at is None:
        return f"{NEVER_ANSWERED} {for_how_long} ago."
    return f"{LAST_ANSWERED} {for_how_long} ago."


def _affected(days: tuple[date, ...]) -> str:
    """Which days hold what the feed already contributed, so the panel says what is in doubt."""
    if not days:
        return NO_DAY_IN_DOUBT
    if len(days) == A_SINGLE_DAY:
        return f"{days[0].isoformat()} {ONE_DAY_HOLDS}"
    return (
        f"{len(days)} days between {days[0].isoformat()} and {days[-1].isoformat()} "
        f"{SEVERAL_DAYS_HOLD}"
    )


class AnchorStarts(Protocol):
    """What the composer needs from the anchor package: when this source's commitments begin.

    Declared here rather than imported, for the reason ``anchor_writing`` declares its own writer:
    the anchor package is not this package's dependency, so the requirement is stated by the caller
    that has it and composition is what puts the two together.
    """

    async def start_instants_for_source(
        self, source_id: CalendarSourceId, *, span: Interval
    ) -> tuple[datetime, ...]: ...


class StaleFeedReading:
    """Every notice this tenant's stale feeds raise, each naming the days it puts in doubt."""

    def __init__(self, anchors: AnchorStarts, *, profile: ZoneProfile, horizon: Interval) -> None:
        self._anchors = anchors
        self._profile = profile
        self._horizon = horizon

    async def of(
        self, sources: Sequence[CalendarSourceRecord], *, now: datetime
    ) -> tuple[Notice, ...]:
        """The notices these sources raise, having read the anchor days of the stale ones only.

        A healthy tenant costs no anchor read at all, which is why the threshold is applied before
        the read rather than after it.

        One read per stale feed, awaited in turn rather than gathered. The repository shares the
        request's session, and a session may not be used concurrently, so the sequence is a
        constraint rather than a missed optimization.
        """
        stale = [source for source in sources if is_feed_stale(source, now=now)]
        if not stale:
            return ()
        span = markable_span(now=now, profile=self._profile, horizon=self._horizon)
        days = {source.id: await self._days_of(source.id, span) for source in stale}
        return stale_feed_notices(stale, days, now=now)

    async def _days_of(self, source_id: CalendarSourceId, span: Interval) -> tuple[date, ...]:
        """The local dates this source's commitments begin on inside ``span``, earliest first.

        A commitment belongs to the day it STARTS in, which is the reading every other day-shaped
        read in this product already uses, so a night's sleep is in doubt on the day it began.

        Sorted here rather than taken from the read's own order, so the claim this module makes
        about the days it names holds whatever order the rows arrive in.
        """
        starts = await self._anchors.start_instants_for_source(source_id, span=span)
        return tuple(sorted({local_date(start, self._profile.home_zone) for start in starts}))
