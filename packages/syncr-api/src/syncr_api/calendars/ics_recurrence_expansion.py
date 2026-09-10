"""Expanding a declared recurrence into wall-time occurrences inside a window.

Expansion owns dates around a parsed rule: ``RDATE`` additions, ``EXDATE`` removals, dateutil's
lazy faults, and clipping to the caller's instant window. Rules are parsed and validated by
:mod:`syncr_api.calendars.ics_recurrence_grammar` before dateutil expands them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dateutil.rrule import rruleset, rrulestr

from syncr_api.calendars.ics_errors import IcsRejection, UnparseableRecurrence
from syncr_api.calendars.ics_recurrence_grammar import (
    _QUOTED_RULE_WIDTH,
    _parse_rule,
    _require_expandable,
    _stated,
    _wall_until,
)
from syncr_api.calendars.ics_times import as_wall, resolve
from syncr_api.calendars.ics_values import ZoneKind

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import date, datetime

    from syncr_api.calendars.ics_values import IcsTime
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile


@dataclass(frozen=True, slots=True)
class Recurrence:
    """The recurrence a master component declares: a rule, extra dates, and exclusions."""

    rule_text: str | None = None
    extra_dates: tuple[IcsTime, ...] = ()
    excluded: tuple[IcsTime, ...] = ()

    @property
    def recurring(self) -> bool:
        return self.rule_text is not None or bool(self.extra_dates)


# What a foreign expander raises when a rule it accepted turns out to be unexpandable. dateutil
# validates lazily, so these arrive during iteration rather than at construction. The set includes
# index failures from dateutil's weekday mask and IcsRejection by inheritance.
_RULE_FAULTS: Final = (ValueError, TypeError, OverflowError, IndexError, KeyError)


def occurrences(
    start: IcsTime,
    recurrence: Recurrence,
    *,
    window: Interval,
    profile: ZoneProfile,
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
    while True:
        try:
            wall = next(candidates)
        except StopIteration:
            break
        except IcsRejection:
            raise
        except _RULE_FAULTS as error:
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
    return tuple(kept)


def _candidates(
    start: IcsTime, *, rule_text: str | None, additions: tuple[datetime, ...]
) -> Iterator[datetime]:
    """Every wall datetime the rule and the extra dates produce, in order."""
    if rule_text is None:
        yield from sorted({start.wall, *additions})
        return
    merged = _parsed_rule(rule_text, start)
    for wall in additions:
        merged.rdate(wall)
    yield from merged


def _parsed_rule(rule_text: str, start: IcsTime) -> rruleset:
    """``rule_text`` as a dateutil rule set anchored at the series' naive start.

    ``forceset`` makes the return one type so callers may add ``RDATE`` values consistently.

    ``unfold=True`` selects dateutil's line-unfolding branch, which does not call ``str.split()``.
    The grammar rejects every ``str.isspace()`` character to protect the whitespace-splitting branch
    should a later caller select it.

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


def _additions(
    extra_dates: Sequence[IcsTime], start: IcsTime, *, window: Interval, profile: ZoneProfile
) -> tuple[datetime, ...]:
    """Every ``RDATE`` inside ``window``, as wall time in the zone the series recurs in."""
    kept: list[datetime] = []
    for extra in extra_dates:
        if extra.kind is ZoneKind.FLOATING:
            kept.append(extra.wall)
            continue
        instant = resolve(extra, profile)
        if window.start <= instant < window.end:
            kept.append(as_wall(instant, zone_of=start, profile=profile))
    return tuple(kept)


def _exclusions(
    excluded: Sequence[IcsTime], profile: ZoneProfile
) -> tuple[frozenset[datetime], frozenset[date]]:
    """The instants and whole dates an ``EXDATE`` list removes."""
    instants: set[datetime] = set()
    dates: set[date] = set()
    for moment in excluded:
        if moment.all_day:
            dates.add(moment.on)
        else:
            instants.add(resolve(moment, profile))
    return frozenset(instants), frozenset(dates)
