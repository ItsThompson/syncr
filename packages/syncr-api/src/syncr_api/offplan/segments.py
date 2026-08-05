"""An off-plan period as the day segments the projection writes, one event per local day.

A period is one arbitrary span with instant precision -- Friday 14:00 to Monday 09:00 is one
declaration -- and the write target carries one event per local day of it. Not one event for the
whole span, because a four-day event on a phone renders as a banner across four days and says
nothing about any of them; and not one event per week either, because the reader's question is
"why is Saturday empty", which is a question about a day.

**A segment breaks at local midnight in the tenant's own zone**, resolved per date through the zone
layer, so a segment containing a daylight-saving transition is as long as that day really was. The
projection horizon is bounded by local midnight in the same zone, so a segment never straddles
either end of the horizon: filtering by overlap is therefore complete, and nothing here clips a
segment to the horizon.

**The first and last segments are partial, and that is the point.** A period starting Friday 14:00
contributes Friday 14:00 to Saturday 00:00, so the event on the phone starts when the user actually
goes off plan rather than at the start of that day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import TYPE_CHECKING

from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.intervals import Interval
from syncr_domain.zones import active_zone, to_instant

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_domain.identifiers import OffPlanPeriodId
    from syncr_domain.zones import Date, ZoneProfile

_ONE_DAY = timedelta(days=1)

LOCAL_MIDNIGHT = time(0, 0)


@dataclass(frozen=True, slots=True)
class OffPlanSegment:
    """One local day's worth of one off-plan period, as the projection intends it."""

    period_id: OffPlanPeriodId
    on: Date
    interval: Interval
    label: str | None = None
    keep_frame: bool = False


def off_plan_segments(
    periods: Iterable[OffPlanPeriodRecord], *, horizon: Interval, profile: ZoneProfile
) -> tuple[OffPlanSegment, ...]:
    """Every day segment of ``periods`` that reaches into ``horizon``, earliest first.

    The periods arrive unclipped, which is what the repository answers with, so the horizon is
    applied here and applied once: to the segments rather than to the periods, because a period
    reaching past the horizon still explains the days of it that are inside.
    """
    return tuple(
        segment
        for period in periods
        for segment in _segments_of(period, profile=profile)
        if segment.interval.overlaps(horizon)
    )


def _segments_of(period: OffPlanPeriodRecord, *, profile: ZoneProfile) -> Iterator[OffPlanSegment]:
    """One segment per local day the period covers, in date order.

    The last date is the one holding the final instant the period COVERS rather than the one
    holding ``end``: the bounds are half-open, so a period ending at a Monday's local midnight
    reaches nothing inside Monday and contributes no Monday segment.
    """
    home = profile.home_zone
    first = local_date(period.interval.start, home)
    # `end` itself is excluded, so a period ending exactly at local midnight ends on the previous
    # day. Stepping back by the shortest representable amount rather than by a fixed quantum keeps
    # that true for a period whose end is not on the grid, which storage forbids and this does not
    # require.
    last = local_date(period.interval.end - timedelta(microseconds=1), home)
    on = first
    while on <= last:
        segment = _day_span(on, profile).clipped_to(period.interval)
        if segment is not None:
            yield OffPlanSegment(
                period_id=period.id,
                on=on,
                interval=segment,
                label=period.label,
                keep_frame=period.keep_frame,
            )
        on += _ONE_DAY


def _day_span(on: Date, profile: ZoneProfile) -> Interval:
    """The whole local day ``on``, in the zone active on it and on the day after.

    Each end resolves against its own date's zone, so a transition day is 23 or 25 hours rather
    than 24. The same reading :mod:`syncr_api.calendars.day_spans` gives a published all-day event,
    and it is stated separately here because that one takes a day COUNT from a provider payload
    while this one walks the days of a span syncr stored.
    """
    tomorrow = on + _ONE_DAY
    return Interval(
        to_instant(LOCAL_MIDNIGHT, on, active_zone(profile, on)),
        to_instant(LOCAL_MIDNIGHT, tomorrow, active_zone(profile, tomorrow)),
    )
