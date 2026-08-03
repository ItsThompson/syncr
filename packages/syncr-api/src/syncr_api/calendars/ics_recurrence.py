"""Expanding a recurring series into the occurrences that fall inside a window.

Recurrence is expanded in **wall time**, in the series' own zone, because that is what RFC
5545 says a rule means: a 09:00 lecture is at 09:00 local on every occurrence, which is two
different instants either side of a daylight-saving boundary. Expanding in UTC would move
half a term's lectures by an hour.

The rule itself is ``dateutil.rrule``'s. RFC 5545 recurrence has a large surface (``BYDAY``,
``BYSETPOS``, ``WKST``, ``COUNT``, ``UNTIL``, ``INTERVAL``) and a second implementation of it
would be wrong in ways only a real feed reveals. What this module owns is everything around
it: normalizing the rule so it can be expanded in wall time at all, merging ``RDATE``,
applying ``EXDATE``, bounding the work, and clipping to the window.

**Normalizing ``UNTIL`` is not optional.** The standard requires a UTC ``UNTIL`` whenever
``DTSTART`` names a zone, and dateutil refuses to mix an aware ``UNTIL`` with a naive
``DTSTART``. So a ``UNTIL`` ending in ``Z`` is resolved to an instant and converted back to
wall time in the series' zone. Dropping the suffix instead would move the boundary by the
zone's offset, which silently keeps or loses the final occurrence of a term.

**The work is bounded.** A rule with no ``COUNT`` and no ``UNTIL`` expands for as long as
anything asks it to, and a feed can carry a ``FREQ=SECONDLY`` rule by mistake. Iteration
stops at a stated step limit and the series is rejected with a reason, rather than holding a
worker tick open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from dateutil.rrule import rruleset, rrulestr

from syncr_api.calendars.ics_errors import UnparseableRecurrence
from syncr_api.calendars.ics_times import resolve
from syncr_api.calendars.ics_values import ZoneKind

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import date

    from syncr_api.calendars.ics_values import IcsTime
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

# How many candidate occurrences one series may be walked through before it is rejected.
# A daily rule running since 2010 needs a few thousand steps to reach a horizon two weeks
# out; a FREQ=SECONDLY rule needs hundreds of millions, and this is what stops it.
MAX_EXPANSION_STEPS: Final = 50_000

_UNTIL: Final = "UNTIL"
_INTERVAL: Final = "INTERVAL"
_RULE_SEPARATOR: Final = ";"
_WALL_FORMAT: Final = "%Y%m%dT%H%M%S"


@dataclass(frozen=True, slots=True)
class Recurrence:
    """The recurrence a master component declares: a rule, extra dates, and exclusions."""

    rule_text: str | None = None
    extra_dates: tuple[IcsTime, ...] = ()
    excluded: tuple[IcsTime, ...] = ()

    @property
    def recurring(self) -> bool:
        return self.rule_text is not None or bool(self.extra_dates)


def occurrences(
    start: IcsTime,
    recurrence: Recurrence,
    *,
    window: Interval,
    profile: ZoneProfile,
    limit: int = MAX_EXPANSION_STEPS,
) -> tuple[datetime, ...]:
    """Every occurrence's wall datetime inside ``window``, exclusions already applied.

    ``window`` is in instants and is the caller's to widen: an occurrence that began before
    the horizon and runs into it is inside the window, so the caller subtracts the series'
    duration from the lower bound before calling.
    """
    excluded_instants, excluded_dates = _exclusions(recurrence.excluded, profile)
    kept: list[datetime] = []
    candidates = _candidates(start, recurrence)
    for _step in range(limit):
        # `next` is called under the bound rather than the loop being driven by the iterator,
        # because a rule can spend unbounded work WITHOUT yielding: dateutil advances by `INTERVAL`,
        # so a zero interval never reaches a new value and a bound on yields never fires. Counting
        # attempts bounds the work whether or not the rule produces anything.
        try:
            wall = next(candidates)
        except StopIteration:
            return tuple(kept)
        except _RULE_FAULTS as error:
            # dateutil validates a rule lazily, so a value it accepted at construction can still be
            # refused here, on the first step that reads it.
            message = f"the recurrence rule cannot be expanded: {error}"
            raise UnparseableRecurrence(message) from error
        instant = resolve(start, profile, wall=wall)
        if instant >= window.end:
            break
        if instant < window.start:
            continue
        if instant in excluded_instants or wall.date() in excluded_dates:
            continue
        kept.append(wall)
    else:
        message = (
            f"the recurrence rule reaches {limit} occurrences without leaving the "
            "window, so syncr will not read it"
        )
        raise UnparseableRecurrence(message)
    return tuple(kept)


def _candidates(start: IcsTime, recurrence: Recurrence) -> Iterator[datetime]:
    """Every wall datetime the rule and the extra dates produce, in order.

    A component with no rule and no extra date is its own single occurrence, so a caller
    needs no branch for the non-recurring case.
    """
    if recurrence.rule_text is None:
        yield from sorted({start.wall, *(extra.wall for extra in recurrence.extra_dates)})
        return
    merged = _parsed_rule(recurrence.rule_text, start)
    for extra in recurrence.extra_dates:
        merged.rdate(extra.wall)
    yield from merged


# What dateutil raises when a rule it accepted turns out to be unexpandable. It validates lazily, so
# these arrive during iteration rather than at construction.
_RULE_FAULTS: Final = (ValueError, TypeError, OverflowError)


def _parsed_rule(rule_text: str, start: IcsTime) -> rruleset:
    """``rule_text`` as a dateutil rule set anchored at the series' naive start.

    ``forceset`` is what makes the return one type rather than two: dateutil answers with a
    bare rule or with a set depending on the input's shape, and the caller needs to add
    ``RDATE`` occurrences to whatever it got.

    dateutil raises a bare ``ValueError`` on a malformed rule, naming neither the property
    nor the feed, so it is re-raised as the package's own rejection.
    """
    _require_positive_interval(rule_text)
    try:
        return rrulestr(_wall_until(rule_text, start), dtstart=start.wall, forceset=True)
    except _RULE_FAULTS as error:
        message = f"{rule_text!r} is not a recurrence rule syncr can expand: {error}"
        raise UnparseableRecurrence(message) from error


def _require_positive_interval(rule_text: str) -> None:
    """Refuse an ``INTERVAL`` that is not a positive number, naming the value.

    RFC 5545 requires a positive integer and dateutil enforces neither bound. A NEGATIVE interval is
    accepted at construction and raises during iteration, from inside dateutil, where the message
    names neither the rule nor the feed. A ZERO interval is worse: dateutil advances by it, so the
    rule never reaches a new value and never terminates. Both are answered here, where the rejection
    can quote the value the feed stated.
    """
    for part in rule_text.split(_RULE_SEPARATOR):
        key, separator, value = part.partition("=")
        if not separator or key.strip().upper() != _INTERVAL:
            continue
        stated = value.strip()
        if not stated.isdigit() or int(stated.lstrip("0") or "0") < 1:
            message = (
                f"the recurrence rule states an INTERVAL of {stated!r}, and an interval has to "
                "be a positive number of periods"
            )
            raise UnparseableRecurrence(message)


def _wall_until(rule_text: str, start: IcsTime) -> str:
    """``rule_text`` with any UTC ``UNTIL`` rewritten as wall time in the series' zone.

    The rule is expanded against a naive ``DTSTART``, and dateutil refuses to compare that
    with an aware ``UNTIL``. Converting through the zone rather than dropping the suffix is
    what keeps the boundary on the occurrence the publisher meant.
    """
    parts = rule_text.split(_RULE_SEPARATOR)
    rewritten: list[str] = []
    for part in parts:
        key, separator, value = part.partition("=")
        if not separator or key.strip().upper() != _UNTIL or not value.strip().endswith("Z"):
            rewritten.append(part)
            continue
        rewritten.append(f"{key}={_as_series_wall(value.strip(), start)}")
    return _RULE_SEPARATOR.join(rewritten)


def _as_series_wall(until: str, start: IcsTime) -> str:
    """A UTC ``UNTIL`` value, read as wall time in the zone the series recurs in."""
    stamped = datetime.strptime(until, f"{_WALL_FORMAT}Z").replace(tzinfo=ZoneInfo("UTC"))
    if start.kind is ZoneKind.UTC:
        return stamped.strftime(_WALL_FORMAT)
    zone = start.zone or "UTC"
    return stamped.astimezone(ZoneInfo(zone)).strftime(_WALL_FORMAT)


def _exclusions(
    excluded: Sequence[IcsTime], profile: ZoneProfile
) -> tuple[frozenset[datetime], frozenset[date]]:
    """The instants and the whole dates an ``EXDATE`` list removes.

    Two sets, because publishers write ``EXDATE`` two ways. The standard requires it to
    match the occurrence exactly, which is the instant set. A publisher that emits a
    date-valued ``EXDATE`` for a timed series meant the whole day, and reading it as
    midnight would exclude nothing at all: an event the user was told is cancelled would
    stay in the plan as immovable occupancy.
    """
    instants: set[datetime] = set()
    dates: set[date] = set()
    for moment in excluded:
        if moment.all_day:
            dates.add(moment.on)
        else:
            instants.add(resolve(moment, profile))
    return frozenset(instants), frozenset(dates)
