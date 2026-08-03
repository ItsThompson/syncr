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
from math import prod
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from dateutil.rrule import rruleset, rrulestr

from syncr_api.calendars.ics_errors import IcsRejection, UnparseableRecurrence
from syncr_api.calendars.ics_times import resolve
from syncr_api.calendars.ics_values import MAX_MAGNITUDE_DIGITS, ZoneKind

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
_SETPOS: Final = "BYSETPOS"
_BYMINUTE: Final = "BYMINUTE"
_BYSECOND: Final = "BYSECOND"
_FREQ: Final = "FREQ"

# Which BY parts EXPAND a period into the set BYSETPOS selects from, at each frequency small enough
# for that set to be enumerable. RFC 5545 section 3.3.10 splits the BY parts two ways per frequency:
# one expands a period into more members, the other LIMITS which periods are considered at all. The
# split moves with the frequency, and BYMINUTE is the trap: it expands an hour into minutes, and
# merely limits which minutes a MINUTELY rule looks at. Counting a limiting part as room overstates
# the set, which is how three of these shapes passed the guard and walked to year 9999 anyway.
_EXPANDING_PARTS: Final = {
    "HOURLY": (_BYMINUTE, _BYSECOND),
    "MINUTELY": (_BYSECOND,),
    "SECONDLY": (),
}
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
        except IcsRejection:
            # This package's own refusal, which is already stated in the reader's language. It
            # reaches here because it is a ValueError by inheritance, and re-wrapping it would
            # prefix a foreign expander's excuse onto a message that already names the property:
            # "the recurrence rule cannot be expanded: the recurrence rule selects position 2 of…".
            raise
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


# What a foreign expander raises when a rule it accepted turns out to be unexpandable. dateutil
# validates lazily, so these arrive during ITERATION rather than at construction, and they are not
# all value errors: it indexes its own weekday mask with the publisher's BYDAY ordinal, so an
# ordinal past the weeks in the period walks off the end and raises IndexError. This is a local set
# for one library's iteration, deliberately NOT `UNREPRESENTABLE`: it says "dateutil cannot expand",
# where the net says "no value syncr can represent".
#
# It admits this package's own rejections too, by inheritance, so the caller re-raises those first
# rather than describing a refusal syncr made as something dateutil could not do.
_RULE_FAULTS: Final = (ValueError, TypeError, OverflowError, IndexError, KeyError)


def _parsed_rule(rule_text: str, start: IcsTime) -> rruleset:
    """``rule_text`` as a dateutil rule set anchored at the series' naive start.

    ``forceset`` is what makes the return one type rather than two: dateutil answers with a
    bare rule or with a set depending on the input's shape, and the caller needs to add
    ``RDATE`` occurrences to whatever it got.

    dateutil raises a bare ``ValueError`` on a malformed rule, naming neither the property
    nor the feed, so it is re-raised as the package's own rejection.
    """
    _require_expandable(rule_text)
    try:
        return rrulestr(_wall_until(rule_text, start), dtstart=start.wall, forceset=True)
    except _RULE_FAULTS as error:
        message = f"{rule_text!r} is not a recurrence rule syncr can expand: {error}"
        raise UnparseableRecurrence(message) from error


def _require_expandable(rule_text: str) -> None:
    """Refuse a rule dateutil cannot expand in bounded time or bounded steps, naming the property.

    Two shapes, both of which defeat a bound on how many occurrences a rule YIELDS, because neither
    yields at all.
    """
    _require_positive_interval(rule_text)
    _require_selectable_setpos(rule_text)


def _require_selectable_setpos(rule_text: str) -> None:
    """Refuse a ``BYSETPOS`` that reaches past the set its own period can hold.

    ``BYSETPOS`` picks the Nth member of each period's expansion. On an hourly, minutely or
    secondly frequency that set is built from at most ``BYMINUTE`` and ``BYSECOND``, so it is tiny
    and a position past it selects NOTHING. dateutil then advances period by period to its own
    maximum year INSIDE ONE STEP: about seventy million iterations, measured at sixty seconds for
    ONE component, with the worker tick and its transaction held open throughout.

    A bound on steps cannot see that, and neither can an ``UNTIL``: dateutil compares against
    ``UNTIL`` only when a period yields a value, so a period that selects nothing never reaches the
    comparison. Measured, an ``UNTIL`` two days out and a ``COUNT`` of five both still walk.

    Which parts count as room is per-frequency and is the whole difficulty: see
    ``_EXPANDING_PARTS``. The position is compared against that size rather than the shape being
    refused outright, so ``FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=2`` still expands its 303
    occurrences: it selects the second of two, which dateutil answers in milliseconds. Only a
    position with nothing to land on is refused.

    A daily or longer frequency is left to dateutil. The same shape produces nothing there too, but
    it terminates, in two seconds at the worst frequency measured, because the periods are large
    enough to reach the year dateutil stops at. The general problem, a foreign expander spending
    unbounded time inside one call, is NOT closed by this and is recorded as a known issue.
    """
    parts = dict(
        part.partition("=")[::2] for part in rule_text.upper().split(_RULE_SEPARATOR) if "=" in part
    )
    positions = parts.get(_SETPOS)
    expanding = _EXPANDING_PARTS.get(parts.get(_FREQ, "").strip())
    if positions is None or expanding is None:
        return
    reach = max((abs(int(value)) for value in positions.split(",") if _signed(value)), default=0)
    room = prod(_members(parts.get(part)) for part in expanding)
    if reach > room:
        message = (
            f"the recurrence rule selects position {reach} of a "
            f"{parts[_FREQ].strip()} period holding {room}, so it produces nothing and "
            "syncr will not expand it"
        )
        raise UnparseableRecurrence(message)


def _members(value: str | None) -> int:
    """How many values a ``BY`` list names, or one when it names none.

    One rather than zero, because an absent part still leaves the period holding the single member
    ``DTSTART`` names.
    """
    if value is None:
        return 1
    return max(len([item for item in value.split(",") if item.strip()]), 1)


def _signed(value: str) -> bool:
    """Whether ``int`` will convert this, bounded so the conversion cannot refuse.

    ``isdecimal`` rather than ``isdigit``, and the difference is the point: ``isdigit`` is true
    for ``'2'`` superscript and for circled digits, which ``int`` then refuses. A feed can carry
    either. Checking the wrong predicate left the conversion able to raise while the table beside it
    claimed the site was guarded here.

    The length bound is the second half. ``int`` refuses a decimal string longer than the
    interpreter's digit limit, so a bound on significant digits is what makes the conversion total.
    """
    stated = value.strip().removeprefix("+").removeprefix("-")
    return stated.isdecimal() and len(stated.lstrip("0")) <= MAX_MAGNITUDE_DIGITS


def _stated(value: str) -> str:
    """How a refused value is named, without quoting a value thousands of characters wide."""
    if len(value) <= MAX_MAGNITUDE_DIGITS:
        return repr(value)
    return f"a value of {len(value)} characters"


def _require_positive_interval(rule_text: str) -> None:
    """Refuse an ``INTERVAL`` that is not a positive number, naming the value.

    RFC 5545 requires a positive integer and dateutil enforces neither bound. A NEGATIVE interval is
    accepted at construction and raises during iteration, from inside dateutil, where the message
    names neither the rule nor the feed. A ZERO interval is worse: dateutil advances by it, so the
    rule never reaches a new value and never terminates. Both are answered here, where the rejection
    can quote the value the feed stated.

    A leading ``+`` is accepted, as dateutil accepts it. The standard does not write the sign, but a
    publisher that does means one, and losing a whole series over it would be the wrong trade.
    """
    for part in rule_text.split(_RULE_SEPARATOR):
        key, separator, value = part.partition("=")
        if not separator or key.strip().upper() != _INTERVAL:
            continue
        stated = value.strip()
        if not _signed(stated) or int(stated.lstrip("0") or "0") < 1:
            message = (
                f"the recurrence rule states an INTERVAL of {_stated(stated)}, and an interval has "
                "to be a positive number of periods"
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
