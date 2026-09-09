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

from syncr_api.calendars.ics_errors import IcsRejection, UnparseableRecurrence
from syncr_api.calendars.ics_times import UTC_ZONE, as_wall, resolve
from syncr_api.calendars.ics_values import MAX_MAGNITUDE_DIGITS, ZoneKind

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
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
# The values RFC 5545 section 3.3.10 allows each numeric rule part, as the closed intervals the
# standard actually gives, one entry per interval.
#
# **Only four of these have a signed form.** BYMONTHDAY, BYYEARDAY, BYWEEKNO and BYSETPOS count
# backwards from the end of their period, so -1 is the correct idiom on all four. BYMONTH, BYHOUR,
# BYMINUTE and BYSECOND are unsigned, so each entry is the interval the standard gives rather than a
# magnitude: comparing magnitudes admits BYMONTH=-1, which no month matches and which does not
# return in three minutes.
#
# Zero is excluded from the signed properties because the standard excludes it and dateutil does
# not: BYMONTHDAY=0 is accepted there and can never match.
#
# BYSECOND reaches 60 because the standard allows a leap second. dateutil is stricter and refuses it
# with its own message, so syncr does not add a second refusal for a value the standard permits.
#
# BYDAY is absent on purpose: it carries weekday codes rather than plain numbers, and dateutil
# validates that one itself.
_RULE_RANGES: Final[dict[str, tuple[tuple[int, int], ...]]] = {
    "BYMONTH": ((1, 12),),
    "BYMONTHDAY": ((-31, -1), (1, 31)),
    "BYYEARDAY": ((-366, -1), (1, 366)),
    "BYWEEKNO": ((-53, -1), (1, 53)),
    "BYHOUR": ((0, 23),),
    "BYMINUTE": ((0, 59),),
    "BYSECOND": ((0, 60),),
    "BYSETPOS": ((-366, -1), (1, 366)),
}
_RULE_SEPARATOR: Final = ";"
_WALL_FORMAT: Final = "%Y%m%dT%H%M%S"

# The longest a single comma-separated member of a rule part may be. Every legitimate member is a
# number, a signed number, or a weekday with an ordinal, so this is far beyond any real one, and it
# is small enough that no conversion of it can depend on the interpreter's digit limit: Python's own
# floor for that limit is 640.
#
# It exists because a rule value is converted TWICE, once here and once by dateutil, and only one of
# those is syncr's to bound. Without it, a value padded past the interpreter's limit meant one thing
# to syncr and was refused by dateutil, so the same feed answered two ways depending on how the
# process was started. Bounding it as a PART of the rule rather than inside a predicate is what
# makes it hold for every property, including the ones no guard reads.
MAX_RULE_ITEM_CHARS: Final = 32

# How much of a refused rule the message quotes. A rule is worth quoting, because the property that
# broke is in it; a rule the publisher padded to eight thousand characters is not, and a detail is
# stored and served rather than logged and dropped.
_QUOTED_RULE_WIDTH: Final = 200


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
    candidates = _candidates(
        start,
        rule_text=recurrence.rule_text,
        additions=_additions(recurrence.extra_dates, start, window=window, profile=profile),
    )
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


def _candidates(
    start: IcsTime, *, rule_text: str | None, additions: tuple[datetime, ...]
) -> Iterator[datetime]:
    """Every wall datetime the rule and the extra dates produce, in order.

    A component with no rule and no extra date is its own single occurrence, so a caller
    needs no branch for the non-recurring case.
    """
    if rule_text is None:
        yield from sorted({start.wall, *additions})
        return
    merged = _parsed_rule(rule_text, start)
    for wall in additions:
        merged.rdate(wall)
    yield from merged


def _additions(
    extra_dates: Sequence[IcsTime], start: IcsTime, *, window: Interval, profile: ZoneProfile
) -> tuple[datetime, ...]:
    """Every ``RDATE`` inside ``window``, as wall time in the zone the series recurs in.

    An ``RDATE`` carrying a ``TZID`` or a ``Z`` suffix states an INSTANT, and expansion runs in the
    series' own wall clock, so each one is resolved in the zone it names and then restated in the
    series'. Merging its wall time as it stands would read a New York value on a London series as a
    London value. The sibling ``EXDATE`` path resolves each value in its own zone already.

    A floating ``RDATE`` names no zone of its own, so it is already on the clock that resolves the
    series and is merged unchanged rather than sent through the profile and back.

    The window is applied to the values that state an instant, because the instant is in hand and a
    date the caller cannot reach needs no wall time at all: one at the end of representable time
    restates into arithmetic that overflows, for a value no window could have placed.
    """
    kept: list[datetime] = []
    for extra in extra_dates:
        if extra.kind is ZoneKind.FLOATING:
            kept.append(extra.wall)
            continue
        instant = resolve(extra, profile)
        if window.start <= instant < window.end:
            kept.append(as_wall(instant, zone_of=start, profile=profile))
    return tuple(kept)


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


@dataclass(frozen=True, slots=True)
class _Rule:
    """One ``RRULE`` value, parsed once into the properties dateutil will read.

    ``text`` is the canonical form handed to the expander and ``parts`` is what the guards read, so
    the rule syncr validates and the rule dateutil expands are the same rule by construction rather
    than by two readers happening to agree.

    That agreement is not free. dateutil calls ``s.split()`` on the value unless it is told to
    unfold, so every whitespace-separated token becomes its own content line: a second ``RRULE``, an
    ``EXRULE``, or a ``DTSTART`` overriding the one syncr resolved. A guard that splits on ``;`` and
    treats whitespace as padding is therefore reading a different rule from the one that expands,
    and one space is enough to separate them.
    """

    text: str
    parts: Mapping[str, str]


def _parse_rule(rule_text: str) -> _Rule:
    """``rule_text`` as one property list, or a rejection naming the part that is not one.

    Three things make the canonical text the same rule dateutil will read, and each closes a door on
    the same seam: syncr and dateutil parsing one string by different grammars.

    **Whitespace.** RFC 5545 gives ``recur`` none at all. Padding around a separator is harmless and
    common, so ``FREQ=WEEKLY; BYDAY=MO`` is stripped and expanded; whitespace INSIDE a name or a
    value is refused, because dateutil splits on it and reads each token as its own content line.

    **The name must be an RFC token.** A name carrying a colon is a second content line to dateutil,
    which splits ``name:value`` before it looks at properties: ``RRULE:FREQ=SECONDLY;BYSETPOS=300``
    reads here as a property called ``RRULE:FREQ``, so ``FREQ`` is absent and every guard that reads
    it declines to judge, while dateutil expands a secondly rule. ``EXRULE:`` is worse than a hang:
    it is an EXCLUSION rule, so the series is deleted with no rejection at all.

    **Case.** dateutil upper-cases every name and value, so comparing either case-sensitively here
    is the same divergence one letter wide: a lowercase ``z`` on an ``UNTIL`` is a UTC value to
    dateutil and a floating one to syncr, which costs the whole series.

    A part with no ``=`` is refused too. dateutil unpacks each part into a pair, so it answers that
    shape with ``not enough values to unpack``, which tells a publisher nothing.
    """
    kept: list[str] = []
    parts: dict[str, str] = {}
    for part in rule_text.strip().split(_RULE_SEPARATOR):
        if not part.strip():
            continue
        name, separator, value = (piece.strip() for piece in part.partition("="))
        if not separator:
            message = (
                f"the recurrence rule states {_stated(name, width=MAX_RULE_ITEM_CHARS)} with no "
                "value, and every part of a rule is a name and a value"
            )
            raise UnparseableRecurrence(message)
        for label, piece in (("name", name), ("value", value)):
            if any(character.isspace() for character in piece):
                message = (
                    f"the recurrence rule states a {label} of "
                    f"{_stated(piece, width=MAX_RULE_ITEM_CHARS)}, and RFC 5545 allows no "
                    "whitespace inside a rule: a second property hides there"
                )
                raise UnparseableRecurrence(message)
        # Checked AFTER the whitespace pass so each cause keeps its own message: a name carrying a
        # space is not a token either, and reporting that as a colon would name the wrong fault.
        if not name.replace("-", "").isalnum():
            message = (
                f"the recurrence rule states a property name of "
                f"{_stated(name, width=MAX_RULE_ITEM_CHARS)}, and a rule property is one name and "
                "one value: a colon there is a second content line, which dateutil reads and the "
                "guards here do not"
            )
            raise UnparseableRecurrence(message)
        kept.append(f"{name.upper()}={value.upper()}")
        parts[name.upper()] = value.upper()
    return _Rule(text=_RULE_SEPARATOR.join(kept), parts=parts)


def _parsed_rule(rule_text: str, start: IcsTime) -> rruleset:
    """``rule_text`` as a dateutil rule set anchored at the series' naive start.

    ``forceset`` is what makes the return one type rather than two: dateutil answers with a
    bare rule or with a set depending on the input's shape, and the caller needs to add
    ``RDATE`` occurrences to whatever it got.

    ``unfold=True`` keeps dateutil on its line-based branch rather than its whitespace-splitting
    one. It is **not** what closes the divergence: measured, removing it leaves every test green,
    because the canonical text carries no whitespace for either branch to differ over. It is kept as
    a second mechanism at the point where the two grammars actually meet, so a future edit that
    loosens the normalisation does not silently reopen the seam.

    The normalisation is the load-bearing half, and its coverage is exact rather than probable:
    ``_parse_rule`` refuses a part containing any ``str.isspace()`` character, and ``str.split()``
    with no argument splits on exactly that set. The two cannot disagree about what a token is.

    dateutil raises a bare ``ValueError`` on a malformed rule, naming neither the property
    nor the feed, so it is re-raised as the package's own rejection.
    """
    rule = _parse_rule(rule_text)
    _require_expandable(rule)
    try:
        return rrulestr(
            _wall_until(rule.text, start), dtstart=start.wall, forceset=True, unfold=True
        )
    except _RULE_FAULTS as error:
        message = (
            f"{_stated(rule_text, width=_QUOTED_RULE_WIDTH)} is not a recurrence rule syncr can "
            f"expand: {error}"
        )
        raise UnparseableRecurrence(message) from error


def _require_expandable(rule: _Rule) -> None:
    """Refuse a rule dateutil cannot expand in bounded time or bounded steps, naming the property.

    Two shapes. One defeats a bound on how many occurrences a rule YIELDS, because it never yields
    at all: a zero or negative ``INTERVAL`` never advances. The other is a value so long that
    whether it converts at all depends on how the process was started.

    A ``BYSETPOS`` reaching past the set its period holds is no longer refused here: it was
    measured to hang inside one ``next()`` call, and the external expansion bound
    (:mod:`syncr_api.calendars.expansion_bound`) now answers it with a stated rejection instead.
    """
    _require_readable_members(rule)
    _require_positive_interval(rule)


def _require_readable_members(rule: _Rule) -> None:
    """Refuse a rule member longer than any real one, and one outside its property's range.

    Applied to EVERY property rather than to the two a guard happens to read, because dateutil reads
    properties syncr has no opinion on and converts them under the same interpreter limit. A bound
    living inside one guard's predicate leaves the others unbounded.
    """
    for name, value in rule.parts.items():
        for stated in value.split(","):
            if len(stated) > MAX_RULE_ITEM_CHARS:
                message = (
                    f"the recurrence rule states a {len(stated)}-character value for "
                    f"{name[:MAX_RULE_ITEM_CHARS] or 'a property'}, and syncr reads at most "
                    f"{MAX_RULE_ITEM_CHARS} characters per value"
                )
                raise UnparseableRecurrence(message)
            _require_value_in_range(name, stated)


def _require_value_in_range(name: str, stated: str) -> None:
    """Refuse a numeric rule member outside the values RFC 5545 gives that property.

    dateutil does not check most of these, and a value outside the range can never match, so the
    rule yields nothing while the expander looks for it: ``FREQ=SECONDLY;BYMONTHDAY=53;BYHOUR=2``
    does not return in twenty minutes, inside one call no bound of syncr's can interrupt. A month
    has at most 31 days, so 53 is a mistake, and refusing it by name is more useful than producing
    nothing.

    **The conversion here is a bare ``int``, not ``_signed``.** ``_signed`` answers a narrower
    question, "is this a magnitude syncr will ACT on", and is false past eleven significant digits,
    so reading its ``False`` as "not a number" skips the check for exactly the values most obviously
    out of range. The caller has already bounded the length, so the conversion cannot depend on the
    interpreter's digit limit.
    """
    intervals = _RULE_RANGES.get(name)
    if intervals is None:
        return
    try:
        value = int(stated)
    except ValueError:
        # Not a number at all. dateutil's own validation answers that, and this function has no
        # opinion on a weekday code or a malformed value.
        return
    if any(low <= value <= high for low, high in intervals):
        return
    allowed = " or ".join(f"{low} to {high}" for low, high in intervals)
    message = (
        f"the recurrence rule states {name}={stated}, and RFC 5545 allows "
        f"{allowed} there, so the rule can never match"
    )
    raise UnparseableRecurrence(message)


def _number(value: str) -> int:
    """A rule value ``_signed`` has accepted, converted exactly as dateutil converts it.

    The same call the library makes, on the same text, so the two cannot read one value as two
    different numbers. ``_signed`` has already bounded the length, so the conversion does not depend
    on the interpreter's digit limit.
    """
    return int(value.strip())


def _signed(value: str) -> bool:
    """Whether this is a number ``_number`` will convert to a magnitude syncr will act on.

    **The predicate is ``int`` itself, bounded, rather than a test that resembles it.** dateutil
    converts these values with ``int``, so a predicate that merely approximates ``int``'s accept set
    disagrees with the library somewhere, and the disagreement is a defect in whichever direction it
    falls: ``str.isdigit`` is true for a superscript two that ``int`` refuses, and ``str.isdecimal``
    is false for ``'2_0'`` that ``int`` accepts as 20. Asking ``int`` cannot disagree with it.

    ``_require_positive_interval`` reads this as a refusal, so a value it rejects is named
    rather than silently dropped. The answer still has to match the library's exactly: a value
    syncr calls unreadable and dateutil converts is a value the guard does not judge.

    The length check comes first, so the conversion cannot depend on the interpreter's digit limit
    whatever order the callers run in, and the magnitude check reads the converted number rather
    than the text.
    """
    stated = value.strip()
    if len(stated) > MAX_RULE_ITEM_CHARS:
        return False
    try:
        number = int(stated)
    except ValueError:
        return False
    return len(str(abs(number))) <= MAX_MAGNITUDE_DIGITS


def _stated(value: str, *, width: int = MAX_MAGNITUDE_DIGITS) -> str:
    """How a refused value is named, without quoting a value the feed chose the length of."""
    if len(value) <= width:
        return repr(value)
    return f"a value of {len(value)} characters"


def _require_positive_interval(rule: _Rule) -> None:
    """Refuse an ``INTERVAL`` that is not a positive number, naming the value.

    RFC 5545 requires a positive integer and dateutil enforces neither bound. A NEGATIVE interval is
    accepted at construction and raises during iteration, from inside dateutil, where the message
    names neither the rule nor the feed. A ZERO interval is worse: dateutil advances by it, so the
    rule never reaches a new value and never terminates. Both are answered here, where the rejection
    can quote the value the feed stated.

    A leading ``+`` is accepted, as dateutil accepts it. The standard does not write the sign, but a
    publisher that does means one, and losing a whole series over it would be the wrong trade.
    """
    stated = rule.parts.get(_INTERVAL)
    if stated is None:
        return
    if not _signed(stated) or _number(stated) < 1:
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
    stamped = datetime.strptime(until, f"{_WALL_FORMAT}Z").replace(tzinfo=ZoneInfo(UTC_ZONE))
    if start.kind is ZoneKind.UTC:
        return stamped.strftime(_WALL_FORMAT)
    zone = start.zone or UTC_ZONE
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
