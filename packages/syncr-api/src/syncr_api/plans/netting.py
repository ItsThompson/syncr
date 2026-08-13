"""What a week has already committed, and the two sets every netting rule counts.

One module, because the whole defect class this arithmetic exists inside is a quantity
netting a different set from the one it is compared against. Both sets are defined here, once,
and every quantity that nets says which of them it took.

```
EVERY placement      every block the live plan holds and every pin, past or future.
                     What the probe's free capacity subtracts, so what the probe's own
                     demands and floor reservations must net

IMMOVABLE only       a placement that has started or is in the past, and a pin.
                     What the solver cannot re-place, so what the solver's own remaining
                     work and floor minutes must net: reserving against a block it is
                     about to discard would let it under-place by whatever the previous
                     solve happened to do
```

**A pin and the live-plan block it pins are one placement.** They are paired by binding and the
pin's interval wins, because that is where the block is. Counted twice, a pinned hour would net
twice out of every quantity that reads it, and the effect would be invisible: every figure would
merely be lower than the truth.

**Attribution and capacity are two separate readings of one placement, and this module carries
both.** A placement's own interval is what capacity counts, whatever the user said happened in it:
a past span sits before ``now`` and cannot hold new work, so returning it to capacity is what would
make skipping work improve a verdict. What a placement attributes to the CONTENT it holds is the
outcome's reading of it, and it comes from :func:`syncr_domain.outcomes.attributed_span`, which owns
that table. A skipped hour therefore stays out of capacity and stops counting toward the task, which
raises the demand by the hour the user said they did not work.

Which placements a figure nets and which span it counts of each are two separate choices, and the
second is made per figure:

```
own span             the time the placement occupies. What capacity, an Area's placed minutes and
                     the solver's remaining work count

attributed span      the time the content was given, out of the table above. The probe's demand
                     counts it clipped at a deadline and split at ``now``; an Area's floor figure
                     counts the part of it the placement's own span holds, so a floor is honoured
                     by work done in time the plan holds and by nothing else
```

**Immovability is decided against ``now``, and ``now`` is the assembler's stamp.** A block that
has started is immovable whether or not it has finished, which is the reading the solver takes
too. So a block starting exactly at ``now`` is immovable, and one starting a minute later is not.

Minutes are counted through :class:`~syncr_domain.intervals.IntervalSet`, so two placements
covering one minute contribute one minute rather than two. That matters for an Area's figure in
particular: a user-authored overlap is legitimate, and a summed pair would let an Area's floor
read as satisfied by time that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind
from syncr_domain.intervals import Interval, IntervalSet, has_started
from syncr_domain.outcomes import attributed_span

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from uuid import UUID

    from syncr_domain.identifiers import AreaId, TaskId
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant
    from syncr_domain.outcomes import RecordedOutcome
    from syncr_domain.plan import PlanDocument
    from syncr_solver.inputs import Pin


@dataclass(frozen=True, slots=True)
class Placement:
    """One committed block: what it holds, when, whose Area, and whether it can move.

    ``attributed`` is the span this placement contributes to the CONTENT it holds, which is its
    own interval unless an outcome said otherwise, and ``None`` when the user said the work was
    not done. Every other field reads the placement as time that is committed, which no outcome
    changes.
    """

    binding: BindingRef
    interval: Interval
    area_id: AreaId | None
    immovable: bool
    attributed: Interval | None


@dataclass(frozen=True, slots=True)
class AttributedMinutes:
    """Minutes placed for one task before one deadline, split at ``now``.

    Two figures rather than a total, because the demand rule takes the greater of recorded
    minutes and the PAST half before adding the future half. A single total could not express
    that: it would either double-count a past block the user has already recorded time
    against, or drop a future block that is genuinely scheduled work.
    """

    past: int
    future: int


def placements(
    live_plan: PlanDocument | None,
    pins: Sequence[Pin],
    *,
    now: Instant,
    outcomes: Sequence[RecordedOutcome] = (),
) -> tuple[Placement, ...]:
    """Every committed block of one week, one per binding, in binding order.

    A pin replaces the live-plan block of the same binding, at the pin's own interval. A pin
    naming a binding the plan does not hold is a placement of its own: the user's edit outlives
    a re-solve that dropped the block.

    An outcome is applied to the placement's FINAL interval, so a pinned block the user marked
    partial attributes its reported minutes from where the pin put it rather than from where the
    solver had. An outcome naming a binding no placement holds is ignored here and retained in
    the log: it is a fact about a week that happened, and there is no longer a placement for it
    to change.
    """
    recorded = {outcome.binding: outcome for outcome in outcomes}
    committed: dict[BindingRef, Placement] = {}
    blocks = () if live_plan is None else live_plan.blocks
    for block in blocks:
        committed[block.binding] = _placed(
            binding=block.binding,
            interval=block.interval,
            area_id=block.area_id,
            immovable=has_started(block.interval, now),
            outcome=recorded.get(block.binding),
        )
    for pin in pins:
        placed = committed.get(pin.binding)
        committed[pin.binding] = _placed(
            binding=pin.binding,
            interval=pin.interval,
            # A pin carries no Area of its own, so a pin whose binding the live plan no longer
            # holds is committed time that NO Area figure sees: the task's remaining work nets it
            # and the Area's placed minutes, floor, and reservation do not. That is a gap rather
            # than a rule, and closing it needs an Area on the pin or a read of the binding's
            # entity, neither of which exists while nothing writes a pin. Ticket 1251 owns it.
            area_id=None if placed is None else placed.area_id,
            immovable=True,
            outcome=recorded.get(pin.binding),
        )
    return tuple(sorted(committed.values(), key=_placement_order))


class PlacedTime:
    """The committed time of one week, indexed by the task and the Area it is placed for.

    Built once per assembly and asked by every quantity that nets, so the two sets are counted
    from one reading of one placement list rather than re-derived per field.
    """

    __slots__ = ("_all_by_area", "_all_by_task", "_immovable_by_area", "_immovable_by_task", "_now")

    def __init__(self, placed: Sequence[Placement], *, now: Instant) -> None:
        self._now = now
        self._all_by_task = _by_task(placed, span=_attributed_span)
        self._immovable_by_task = _by_task(
            (item for item in placed if item.immovable), span=_own_span
        )
        self._all_by_area = _by_area(placed, span=_own_span)
        self._immovable_by_area = _by_area(
            (item for item in placed if item.immovable), span=_worked_span
        )

    def immovable_minutes_of_task(self, task_id: TaskId) -> int:
        """Minutes placed for this task the solver cannot re-place. The SOLVER's set.

        Taken over each placement's OWN span rather than over what it attributes, so an outcome
        does not change this figure. Whether it should is not settled: a skipped past block is
        time the solver cannot re-place AND work that was not done, so the two readings disagree
        and only one of them is the probe's. Ticket 1320 owns the question.
        """
        return _minutes(self._immovable_by_task.get(task_id))

    def minutes_of_area(self, area_id: AreaId) -> int:
        """Minutes placed in this Area by any block, pinned or not, past or future."""
        return _minutes(self._all_by_area.get(area_id))

    def immovable_minutes_of_area(self, area_id: AreaId) -> int:
        """Minutes placed in this Area the solver cannot re-place. The SOLVER's set.

        Counted over the part of each placement's attributed span its own interval holds, so an
        hour the user said they did not work honours no floor and the minutes the solver must still
        place rise by it. A pinned hour still to come counts in full: the solver may not move it, so
        it is an hour of the floor it does not have to find room for.
        """
        return _minutes(self._immovable_by_area.get(area_id))

    def attributed_to_task_before(self, task_id: TaskId, deadline: Instant) -> AttributedMinutes:
        """Minutes attributed to this task before ``deadline``, split at ``now``. EVERY placement.

        A placement straddling the deadline contributes the part of it that falls before:
        an hour begun before a deadline and finished after it did half an hour of the work.
        The same clip applies at ``now``, so a block running across the current instant is
        past for the minutes that have elapsed and future for the rest.

        What each placement contributes is the outcome's reading of it, which is why an hour
        moved to Saturday satisfies a Friday deadline no more than an hour planned there would:
        the clip is applied to the span the user gave rather than to the span that was planned.
        """
        placed = self._all_by_task.get(task_id)
        if placed is None:
            return AttributedMinutes(past=0, future=0)
        before = _clipped_before(placed, deadline)
        return AttributedMinutes(
            past=_minutes(_clipped_before(before, self._now)),
            future=_minutes(_clipped_after(before, self._now)),
        )


def _placed(
    *,
    binding: BindingRef,
    interval: Interval,
    area_id: AreaId | None,
    immovable: bool,
    outcome: RecordedOutcome | None,
) -> Placement:
    """One placement, with the attribution table applied to its final interval."""
    return Placement(
        binding=binding,
        interval=interval,
        area_id=area_id,
        immovable=immovable,
        attributed=attributed_span(interval, outcome),
    )


def _own_span(placed: Placement) -> Interval | None:
    """The time this placement occupies: what capacity and an Area's placed minutes count."""
    return placed.interval


def _attributed_span(placed: Placement) -> Interval | None:
    """The time this placement counts toward its content, which an outcome decides."""
    return placed.attributed


def _worked_span(placed: Placement) -> Interval | None:
    """The time this placement gave its Area inside the span it occupies.

    The attributed span narrowed to the placement's own interval, because an Area's floor is
    honoured by work the user did in time the plan holds. An outcome moving an hour to a span this
    placement does not cover honours no floor here, so the solver still owes those minutes, which is
    the direction a floor may safely be wrong in.
    """
    return None if placed.attributed is None else placed.attributed.clipped_to(placed.interval)


def _placement_order(placed: Placement) -> tuple[Instant, Instant, str, str]:
    """A total order over placements: when, then what. Reproducible across two assemblies."""
    return (
        placed.interval.start,
        placed.interval.end,
        placed.binding.kind.value,
        f"{placed.binding.entity_id}\x1f{placed.binding.occurrence_key}",
    )


def _by_task(
    placed: Iterable[Placement], *, span: Callable[[Placement], Interval | None]
) -> Mapping[UUID, IntervalSet]:
    """The placements of each task, unioned. A chunk of a divided task is that task's.

    ``span`` is the caller's reading of a placement, injected rather than branched on, because the
    two readings exist for opposite reasons: the solver's figure counts time it cannot re-place
    and the probe's counts work that was done. A placement whose span reads as nothing under the
    caller's reading contributes nothing.
    """
    return _grouped(
        (item.binding.entity_id, taken)
        for item in placed
        if item.binding.kind is BindingKind.TASK and (taken := span(item)) is not None
    )


def _by_area(
    placed: Iterable[Placement], *, span: Callable[[Placement], Interval | None]
) -> Mapping[UUID, IntervalSet]:
    """The placements of each Area, unioned. The frame and an anchor carry none.

    ``span`` is the caller's reading of a placement, injected for the same reason ``_by_task`` takes
    one: the Area's two figures ask opposite questions of one placement, and one asks what it
    occupies while the other asks what the user gave the Area inside it.
    """
    return _grouped(
        (item.area_id, taken)
        for item in placed
        if item.area_id is not None and (taken := span(item)) is not None
    )


def _grouped(pairs: Iterable[tuple[UUID, Interval]]) -> Mapping[UUID, IntervalSet]:
    collected: dict[UUID, list[Interval]] = {}
    for key, interval in pairs:
        collected.setdefault(key, []).append(interval)
    return {key: IntervalSet(intervals) for key, intervals in collected.items()}


def _minutes(placed: IntervalSet | None) -> int:
    return 0 if placed is None else placed.total_minutes()


def _clipped_before(placed: IntervalSet, moment: Instant) -> IntervalSet:
    """The part of ``placed`` that falls before ``moment``. Empty when none of it does."""
    members = placed.members
    if not members or moment <= members[0].start:
        return IntervalSet()
    return placed.clip(Interval(members[0].start, moment))


def _clipped_after(placed: IntervalSet, moment: Instant) -> IntervalSet:
    """The part of ``placed`` that falls at or after ``moment``. Empty when none of it does."""
    members = placed.members
    if not members or members[-1].end <= moment:
        return IntervalSet()
    return placed.clip(Interval(moment, members[-1].end))
