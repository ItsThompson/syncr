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

    The last date walked is the one ``end`` falls on, and the day it contributes may be empty: the
    bounds are half-open, so a period ending at a Monday's local midnight covers nothing inside
    Monday and the clip below answers with nothing for it. Stating that through the clip rather than
    by stepping the date back is one rule instead of two, and the two cannot then disagree.
    """
    home = profile.home_zone
    on = local_date(period.interval.start, home)
    last = local_date(period.interval.end, home)
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

    Each end resolves against its OWN date's zone, which is what makes the span as long as that day
    really was: a day whose successor is in another zone -- the last day before a trip, the last day
    of one -- is shorter or longer than 24 hours, and reading one zone for both ends would place the
    segment's end at the wrong instant by the offset between them.

    The same reading :mod:`syncr_api.calendars.day_spans` gives a published all-day event, and it is
    stated separately here because that one takes a day COUNT from a provider payload while this one
    walks the days of a span syncr stored.
    """
    tomorrow = on + _ONE_DAY
    return Interval(
        to_instant(LOCAL_MIDNIGHT, on, active_zone(profile, on)),
        to_instant(LOCAL_MIDNIGHT, tomorrow, active_zone(profile, tomorrow)),
    )
