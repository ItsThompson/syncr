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

**Immovability is decided against ``now``, and ``now`` is the assembler's stamp.** A block that
has started is immovable whether or not it has finished, which is the reading H10 takes. So a
block starting exactly at ``now`` is immovable, and one starting a minute later is not.

Minutes are counted through :class:`~syncr_domain.intervals.IntervalSet`, so two placements
covering one minute contribute one minute rather than two. That matters for an Area's figure in
particular: a user-authored overlap is legitimate, and a summed pair would let an Area's floor
read as satisfied by time that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind
from syncr_domain.intervals import Interval, IntervalSet

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from uuid import UUID

    from syncr_domain.identifiers import AreaId, TaskId
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant
    from syncr_domain.plan import PlanDocument
    from syncr_solver.inputs import Pin


@dataclass(frozen=True, slots=True)
class Placement:
    """One committed block: what it holds, when, whose Area, and whether it can move."""

    binding: BindingRef
    interval: Interval
    area_id: AreaId | None
    immovable: bool


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
    live_plan: PlanDocument | None, pins: Sequence[Pin], *, now: Instant
) -> tuple[Placement, ...]:
    """Every committed block of one week, one per binding, in binding order.

    A pin replaces the live-plan block of the same binding, at the pin's own interval. A pin
    naming a binding the plan does not hold is a placement of its own: the user's edit outlives
    a re-solve that dropped the block.
    """
    committed: dict[BindingRef, Placement] = {}
    blocks = () if live_plan is None else live_plan.blocks
    for block in blocks:
        committed[block.binding] = Placement(
            binding=block.binding,
            interval=block.interval,
            area_id=block.area_id,
            immovable=_has_started(block.interval, now),
        )
    for pin in pins:
        placed = committed.get(pin.binding)
        committed[pin.binding] = Placement(
            binding=pin.binding,
            interval=pin.interval,
            # A pin carries no Area of its own, so a pin whose binding the live plan no longer
            # holds is committed time that NO Area figure sees: the task's remaining work nets it
            # and the Area's placed minutes, floor, and reservation do not. That is a gap rather
            # than a rule, and closing it needs an Area on the pin or a read of the binding's
            # entity, neither of which exists while nothing writes a pin. Ticket 1251 owns it.
            area_id=None if placed is None else placed.area_id,
            immovable=True,
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
        self._all_by_task = _by_task(placed)
        self._immovable_by_task = _by_task(item for item in placed if item.immovable)
        self._all_by_area = _by_area(placed)
        self._immovable_by_area = _by_area(item for item in placed if item.immovable)

    def immovable_minutes_of_task(self, task_id: TaskId) -> int:
        """Minutes placed for this task the solver cannot re-place. The SOLVER's set."""
        return _minutes(self._immovable_by_task.get(task_id))

    def minutes_of_area(self, area_id: AreaId) -> int:
        """Minutes placed in this Area by any block, pinned or not, past or future."""
        return _minutes(self._all_by_area.get(area_id))

    def immovable_minutes_of_area(self, area_id: AreaId) -> int:
        """Minutes placed in this Area the solver cannot re-place. The SOLVER's set."""
        return _minutes(self._immovable_by_area.get(area_id))

    def attributed_to_task_before(self, task_id: TaskId, deadline: Instant) -> AttributedMinutes:
        """Minutes placed for this task before ``deadline``, split at ``now``. EVERY placement.

        A placement straddling the deadline contributes the part of it that falls before:
        an hour begun before a deadline and finished after it did half an hour of the work.
        The same clip applies at ``now``, so a block running across the current instant is
        past for the minutes that have elapsed and future for the rest.
        """
        placed = self._all_by_task.get(task_id)
        if placed is None:
            return AttributedMinutes(past=0, future=0)
        before = _clipped_before(placed, deadline)
        return AttributedMinutes(
            past=_minutes(_clipped_before(before, self._now)),
            future=_minutes(_clipped_after(before, self._now)),
        )


def _has_started(interval: Interval, now: Instant) -> bool:
    """Whether the solver may no longer move this block, which H10 decides against ``now``."""
    return interval.start <= now


def _placement_order(placed: Placement) -> tuple[Instant, Instant, str, str]:
    """A total order over placements: when, then what. Reproducible across two assemblies."""
    return (
        placed.interval.start,
        placed.interval.end,
        placed.binding.kind.value,
        f"{placed.binding.entity_id}\x1f{placed.binding.occurrence_key}",
    )


def _by_task(placed: Iterable[Placement]) -> Mapping[UUID, IntervalSet]:
    """The placements of each task, unioned. A chunk of a divided task is that task's."""
    return _grouped(
        (item.binding.entity_id, item.interval)
        for item in placed
        if item.binding.kind is BindingKind.TASK
    )


def _by_area(placed: Iterable[Placement]) -> Mapping[UUID, IntervalSet]:
    """The placements of each Area, unioned. The frame and an anchor carry none."""
    return _grouped((item.area_id, item.interval) for item in placed if item.area_id is not None)


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
