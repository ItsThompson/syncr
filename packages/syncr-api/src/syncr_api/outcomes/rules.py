"""What a request has to satisfy, and the status each rejection carries.

No rule here is stated for the first time. The outcome rules are ``syncr_domain.outcomes``': a
``partial`` states its minutes, a ``moved`` states the interval it really happened in, and neither
figure may appear on a state that does not name it. What lives here is the translation from a domain
rejection into the status the boundary owes it, plus the three refusals the boundary itself owns: a
date that names no day, a day the user has not lived yet, and a range wider than the count that
offered it.

Every rejection here is a bad value in the request, so 422. There is no conflict to answer with:
recording an outcome replaces whatever the block said before, and confirming a day that is already
confirmed is a request that has already succeeded rather than one the stored state refuses.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_api.outcomes.config import MAX_CONFIRM_RANGE_DAYS
from syncr_api.outcomes.days import day_span
from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.intervals import IntervalError
from syncr_domain.outcomes import OutcomeError
from syncr_domain.zones import active_zone

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from syncr_domain.intervals import Interval
    from syncr_domain.zones import Date, ZoneProfile

STATE_FIELD = "state"
DATE_FIELD = "date"
FROM_FIELD = "from"
TO_FIELD = "to"


@contextmanager
def stated_rejection() -> Iterator[None]:
    """Turn an outcome rejection into the status the boundary owes it.

    ``IntervalError`` is caught alongside, because a ``moved`` outcome's interval is built here
    from two instants the request sent and the interval algebra is what refuses a reversed or
    zero-length pair. Both are the same kind of mistake to a caller: a figure the state cannot
    hold.
    """
    try:
        yield
    except (OutcomeError, IntervalError) as error:
        raise ValidationFailed(
            f"That outcome was not accepted: {error}. Nothing was changed, and the block still "
            "reads as it did. A 'partial' outcome states how many minutes it really took and a "
            "'moved' one states the interval it really happened in; no other state carries "
            "either figure.",
            errors=[FieldError(field=STATE_FIELD, message=str(error))],
        ) from error


def require_a_dated_span(on: Date, profile: ZoneProfile, *, field: str) -> Interval:
    """The instants ``on`` covers, or the 422 a date whose midnights are one instant carries.

    Reachable rather than theoretical. ``Pacific/Apia`` skipped 30 December 2011 when it crossed
    the date line, and a travel override moving a clock far enough east removes a date the same
    way. There is nothing to render and nothing to answer for, so the honest answer names the date
    and the zone rather than an empty ledger, which would read as a day with no plan.
    """
    span = day_span(on, profile)
    if span is not None:
        return span
    detail = (
        f"{on.isoformat()} does not exist in {active_zone(profile, on)}: local midnight on that "
        "date and local midnight on the next name the same instant, so the day has no length. "
        "Nothing was changed. Read or confirm the day either side of it."
    )
    raise ValidationFailed(detail, errors=[FieldError(field=field, message="names no day")])


def require_a_day_that_has_begun(
    on: Date, profile: ZoneProfile, now: datetime, *, field: str
) -> None:
    """A day the user has not lived yet cannot be answered for.

    Confirming a day converts presumption into record, and a day that has not begun has nothing to
    presume: recording it would assert that blocks happened before they did. Today itself is
    confirmable, which is what the evening pass is, so the bound is the date and not the instant.
    """
    today = local_date(now, profile.home_zone)
    if on <= today:
        return
    detail = (
        f"{on.isoformat()} has not begun yet, and confirming a day records what happened in it. "
        f"Nothing was changed. Today is {today.isoformat()}, and any day up to and including it "
        "can be confirmed at any later time."
    )
    raise ValidationFailed(detail, errors=[FieldError(field=field, message="is in the future")])


def require_a_range_that_can_be_confirmed(
    first: Date, last: Date, profile: ZoneProfile, now: datetime
) -> None:
    """The three bounds a backfill's range has to satisfy, in the order a caller would hit them."""
    if last < first:
        raise _a_range_that_runs_backward(first, last)
    if (last - first).days + 1 > MAX_CONFIRM_RANGE_DAYS:
        raise _a_range_that_is_too_wide(first, last)
    require_a_day_that_has_begun(first, profile, now, field=FROM_FIELD)
    require_a_day_that_has_begun(last, profile, now, field=TO_FIELD)


def _a_range_that_runs_backward(first: Date, last: Date) -> ValidationFailed:
    """A backfill covers days from the first to the last, both included."""
    detail = (
        f"A backfill runs forward, and this one ended on {last.isoformat()} after starting on "
        f"{first.isoformat()}. Nothing was changed. Both dates are included, so one day is the "
        "same date twice."
    )
    return ValidationFailed(detail, errors=[FieldError(field=TO_FIELD, message="is before `from`")])


def _a_range_that_is_too_wide(first: Date, last: Date) -> ValidationFailed:
    """A backfill is bounded by the same window the count of unconfirmed days reads."""
    covered = (last - first).days + 1
    detail = (
        f"A backfill may cover at most {MAX_CONFIRM_RANGE_DAYS} days and this one covered "
        f"{covered}. Nothing was changed. That is the window the count of unconfirmed days is "
        "taken over, so a wider range covers days the count could not have offered. Confirm it "
        "in shorter ranges: every day inside each of them is still settled."
    )
    return ValidationFailed(
        detail, errors=[FieldError(field=TO_FIELD, message="is too far after `from`")]
    )
