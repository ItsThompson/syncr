"""Reading recurrence grammar into the canonical rule dateutil expands.

The parser keeps syncr's validation and dateutil's grammar aligned. It normalizes a UTC
``UNTIL`` into the series wall time because dateutil expands against a naive ``DTSTART``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from syncr_api.calendars.ics_errors import UnparseableRecurrence
from syncr_api.calendars.ics_times import UTC_ZONE
from syncr_api.calendars.ics_values import MAX_MAGNITUDE_DIGITS, ZoneKind

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.calendars.ics_values import IcsTime

_UNTIL: Final = "UNTIL"
_INTERVAL: Final = "INTERVAL"
# The numeric properties whose invalid values dateutil rejects before the external deadline.
# Refusing them here attributes the problem to the property the publisher supplied instead of
# returning a library error. It is attribution, not protection.
#
# Each value is an RFC 5545 closed interval. BYMONTHDAY and BYSETPOS count backwards from the end
# of their period, so -1 is valid. Zero is excluded from the signed properties because the standard
# excludes it, although dateutil accepts BYMONTHDAY=0. BYSECOND reaches 60 for leap seconds.
#
# BYMONTH, BYYEARDAY, and BYWEEKNO are absent because their invalid values hang until the external
# deadline. BYDAY carries weekday codes rather than plain numbers, so dateutil validates it.
_RULE_RANGES: Final[dict[str, tuple[tuple[int, int], ...]]] = {
    "BYMONTHDAY": ((-31, -1), (1, 31)),
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


def _require_expandable(rule: _Rule) -> None:
    """Refuse rule members that need a stated rejection before dateutil reads them.

    ``INTERVAL`` has its own guard because a negative value raises during dateutil iteration without
    naming the rule or the feed. Member length is bounded before any numeric conversion, so that
    conversion cannot depend on the interpreter configuration.
    """
    _require_readable_members(rule)
    _require_nonnegative_interval(rule)


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
    """Refuse retained numeric members by property instead of a foreign library error.

    Each property in :data:`_RULE_RANGES` has an invalid value that raises before the external
    deadline. This guard is attribution, not protection: it keeps that refusal in the publisher's
    terms. Properties whose invalid values run until the deadline have no entry, so the deadline
    quotes the bounded rule text instead.

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

    ``_require_nonnegative_interval`` reads this as a refusal, so a value it rejects is named
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


def _require_nonnegative_interval(rule: _Rule) -> None:
    """Refuse an ``INTERVAL`` dateutil cannot expand, quoting the stated value.

    A zero interval reaches the external deadline, which quotes the bounded rule text. A negative
    interval raises during dateutil iteration without naming the rule or the feed. This guard
    remains for attribution, not protection: it states which interval value the publisher needs to
    correct.

    A leading ``+`` is accepted, as dateutil accepts it. The standard does not write the sign, but a
    publisher that does means one, and losing a whole series over it would be the wrong trade.
    """
    stated = rule.parts.get(_INTERVAL)
    if stated is None:
        return
    if not _signed(stated) or _number(stated) < 0:
        message = (
            f"the recurrence rule states an INTERVAL of {_stated(stated)}, and an interval has "
            "to be a non-negative number of periods"
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
