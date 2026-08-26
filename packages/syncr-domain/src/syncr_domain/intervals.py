"""Half-open interval arithmetic: the most reused computation in syncr.

The budget denominator, the feasibility probe, and the solver's constraint checker
all share this module, so a wrong answer here is a plausible-looking budget report
rather than a crash. That is the failure mode this product cannot detect any other
way, which is why one rule holds everywhere:

**The interval algebra is never mocked, in any layer.** A faked ``IntervalSet`` in
a service test lets the service pass while the arithmetic underneath it is wrong.
Every caller, at every layer, uses this implementation.

Two properties carry the weight:

*Half-open.* ``[start, end)``, so ``[09:00, 10:00)`` and ``[10:00, 11:00)`` do not
overlap and a zero-length interval cannot be built.

*Normalized on construction.* An ``IntervalSet``'s members are sorted, disjoint,
and merged, so there is no denormalized state to reason about and
``a.union(a) == a``. That idempotence is what keeps the budget denominator safe
against double-counting a frame span that sits inside an off-plan period.

An instant is a UTC datetime. Wall time is not an instant: it becomes one only
through :func:`syncr_domain.zones.to_instant`, which is where a daylight-saving
transition is resolved. Minute counts here are therefore elapsed minutes, so a
transition inside a set is counted correctly with no special case.

The boundary predicates :func:`has_started` and :func:`has_elapsed`, and their far-bound
counterpart :func:`has_ended`, live here for the same reason the arithmetic does. The first
two answer whether a reference instant has reached an interval, they disagree at exactly one
instant, and the api and the solver both ask the question; the third answers whether every
minute of an interval is behind it. A second spelling of any of them inside a caller is how
the two packages come to answer the question differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syncr_domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

type Instant = datetime

_ONE_MINUTE = timedelta(minutes=1)


class IntervalError(DomainError):
    """An interval's invariants reject the given bounds."""


def as_instant(value: datetime) -> Instant:
    """The UTC reading of an aware datetime.

    Instants are stored and compared in UTC. Any aware datetime names one, so the
    conversion happens here rather than at each call site. A naive datetime names
    no instant at all and is rejected: silently assuming a zone is how a
    transition-week bug becomes invisible.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise IntervalError(f"{value!r} carries no time zone, so it names no instant")
    return value.astimezone(UTC)


def _whole_minutes(elapsed: timedelta) -> int:
    """Elapsed whole minutes, dropping any sub-minute remainder.

    Callers snap to the quarter hour and imported anchors are minute-precise, so a
    remainder means sub-minute input. Truncating the summed total once keeps the
    error below one minute for a whole set rather than compounding per member.
    """
    return elapsed // _ONE_MINUTE


@dataclass(frozen=True, order=True)
class Interval:
    """A half-open span of time, ``[start, end)``, ordered by start then end."""

    start: Instant
    end: Instant

    def __post_init__(self) -> None:
        start = as_instant(self.start)
        end = as_instant(self.end)
        if start >= end:
            raise IntervalError(f"an interval needs start < end, got [{start}, {end})")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def total_minutes(self) -> int:
        return _whole_minutes(self.duration)

    def overlaps(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end

    def clipped_to(self, bound: Interval) -> Interval | None:
        """The part of this interval inside ``bound``, or ``None`` when it holds none.

        The single-member form of :meth:`IntervalSet.clip`, and the two are crossed against each
        other in the suite rather than one being written in terms of the other, because the set's
        is a merge walk over many members and this is a comparison of two pairs.

        ``None`` rather than an empty interval, because there is no such value: an interval
        abutting the bound covers no minute of it, and the algebra refuses a zero-length span by
        construction. So the bounds are compared before one is built.
        """
        start = max(self.start, bound.start)
        end = min(self.end, bound.end)
        return Interval(start, end) if start < end else None


def has_started(interval: Interval, now: Instant) -> bool:
    """Whether ``now`` has reached this interval's start.

    Inclusive, so an interval opening exactly at ``now`` has started.
    """
    return interval.start <= now


def has_elapsed(interval: Interval, now: Instant) -> bool:
    """Whether any of this interval has been spent by ``now``.

    Exclusive, so an interval opening exactly at ``now`` has spent none of itself.

    **The pair disagrees at exactly one instant, and both readings are load-bearing there.**
    At an interval's own start there is nothing spent for a record to account for, and it is also no
    longer a change the product may make. A rule about what a record may state takes this reading; a
    rule about what may still be decided takes :func:`has_started`. One predicate serving both makes
    one of the two rules wrong at that instant.
    """
    return interval.start < now


def has_ended(interval: Interval, now: Instant) -> bool:
    """Whether every minute of this interval lies behind ``now``.

    Inclusive of the end, because the interval is half-open: ``[09:00, 10:00)`` holds no
    minute at 10:00, so an interval closing exactly at ``now`` has nothing left ahead of it.
    """
    return interval.end <= now


def _merge(ordered: Sequence[Interval]) -> tuple[Interval, ...]:
    """Merge a start-ordered sequence into disjoint, non-adjacent members.

    Adjacent members merge as well as overlapping ones: ``[09:00, 10:00)`` and
    ``[10:00, 11:00)`` cover the same minutes as ``[09:00, 11:00)``, and one member
    per covered run is the only representation with no choices left in it.
    """
    merged: list[Interval] = []
    for interval in ordered:
        previous = merged[-1] if merged else None
        if previous is None or interval.start > previous.end:
            merged.append(interval)
        elif interval.end > previous.end:
            merged[-1] = Interval(previous.start, interval.end)
    return tuple(merged)


def _without(member: Interval, cuts: Sequence[Interval]) -> Iterator[Interval]:
    """The parts of ``member`` that ``cuts`` does not cover.

    ``cuts`` is a normalized set's members, so it is sorted and disjoint. A cut that
    misses ``member`` removes nothing, which is what makes subtraction total.
    """
    start = member.start
    for cut in cuts:
        if cut.end <= start:
            continue
        if cut.start >= member.end:
            break
        if cut.start > start:
            yield Interval(start, cut.start)
        start = cut.end
        if start >= member.end:
            return
    if start < member.end:
        yield Interval(start, member.end)


class IntervalSet:
    """A normalized, disjoint, sorted set of intervals.

    Construction normalizes, so every operation returns a canonical value and two
    sets covering the same minutes are equal whatever order they were built in.
    """

    __slots__ = ("_members",)

    def __init__(self, intervals: Iterable[Interval] = ()) -> None:
        self._members = _merge(sorted(intervals))

    @property
    def members(self) -> tuple[Interval, ...]:
        return self._members

    def __iter__(self) -> Iterator[Interval]:
        return iter(self._members)

    def __len__(self) -> int:
        return len(self._members)

    def __bool__(self) -> bool:
        return bool(self._members)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IntervalSet):
            return NotImplemented
        return self._members == other._members

    def __hash__(self) -> int:
        return hash(self._members)

    def __repr__(self) -> str:
        return f"IntervalSet({list(self._members)!r})"

    def union(self, other: IntervalSet) -> IntervalSet:
        return IntervalSet((*self._members, *other._members))

    def subtract(self, other: IntervalSet) -> IntervalSet:
        return IntervalSet(
            piece for member in self._members for piece in _without(member, other._members)
        )

    def intersect(self, other: IntervalSet) -> IntervalSet:
        common: list[Interval] = []
        mine, theirs = iter(self._members), iter(other._members)
        left, right = next(mine, None), next(theirs, None)
        while left is not None and right is not None:
            start, end = max(left.start, right.start), min(left.end, right.end)
            if start < end:
                common.append(Interval(start, end))
            if left.end <= right.end:
                left = next(mine, None)
            else:
                right = next(theirs, None)
        return IntervalSet(common)

    def clip(self, bound: Interval) -> IntervalSet:
        return self.intersect(IntervalSet([bound]))

    def before(self, moment: Instant) -> IntervalSet:
        """The part of this set that falls before ``moment``.

        A clip against an unbounded side, which :meth:`clip` cannot express: there is no
        interval reaching to the beginning of time, so a member is kept whole, cut at the
        instant, or dropped. With :meth:`after` it partitions the set, and the suite asserts
        that rather than either being written in terms of the other.
        """
        return IntervalSet(
            member if member.end <= moment else Interval(member.start, moment)
            for member in self._members
            if member.start < moment
        )

    def after(self, moment: Instant) -> IntervalSet:
        """The part of this set that falls at or after ``moment``.

        Half-open on the same side the rest of the algebra is: a member ending exactly at
        ``moment`` holds no minute of what follows it, and one starting there is kept whole.
        """
        return IntervalSet(
            member if member.start >= moment else Interval(moment, member.end)
            for member in self._members
            if member.end > moment
        )

    def total_minutes(self) -> int:
        return _whole_minutes(sum((member.duration for member in self._members), timedelta()))

    def gaps(self, within: Interval, min_minutes: int = 0) -> IntervalSet:
        """The uncovered parts of ``within``, keeping only those long enough to use."""
        uncovered = IntervalSet([within]).subtract(self)
        return IntervalSet(member for member in uncovered if member.total_minutes() >= min_minutes)

    def overlaps(self, probe: Interval) -> bool:
        return any(member.overlaps(probe) for member in self._members)
