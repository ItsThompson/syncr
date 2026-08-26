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

**An orphan pin takes its Area from its binding's entity.** A pin carries no Area of its own, so
one whose binding the live plan no longer holds reads it through ``areas_of``, which answers from
the tasks, habits, and template entries the assembler has already loaded. Its minutes are
committed time whatever the re-solve that dropped the block did, so they stay minutes some Area's
figures see rather than falling out of every one of them.

**Attribution and capacity are two separate readings of one placement, and this module carries
both.** A placement's own interval is what capacity counts, whatever the user said happened in it:
a past span sits before ``now`` and cannot hold new work, so returning it to capacity is what would
make skipping work improve a verdict. What a placement attributes to the CONTENT it holds is the
outcome's reading of it, and it comes from :func:`syncr_domain.outcomes.attributed_span`, which owns
that table. A skipped hour therefore stays out of capacity and stops counting toward the task, which
raises the demand by the hour the user said they did not work, and stops crediting an Area's figures
for the part of the hour that has already gone by.

Which placements a figure nets and which span it counts of each are two separate choices, and the
second is made per figure:

```
own span             the time the placement occupies. What capacity counts
attributed span      the time the content was given, out of the table above. The probe's demand
                     counts it clipped at a deadline and split at ``now``; the solver's remaining
                     work counts the part of it at or before ``now``, so a confirmed skip stops
                     counting as work done; an Area's floor figure counts the part of it the
                     placement's own span holds, so a floor is honoured by work done in time the
                     plan holds and by nothing else

area minutes         an Area's placed figure and its reservation's reading of one placement,
                     split at ``now``: the outcome's answer for the part behind ``now``, and the
                     placement's own span for the part still ahead of it. Behind ``now`` the
                     attribution table is what says the work happened, so a skipped hour stops
                     crediting the reservation; ahead of ``now`` the own span is what ``free``
                     subtracts, so the reservation and free capacity keep counting one set
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
from types import MappingProxyType
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind
from syncr_domain.intervals import Interval, IntervalSet, has_elapsed, has_ended, has_started
from syncr_domain.outcomes import attributed_span
from syncr_domain.templates import TemplateEntryKind

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from typing import Protocol
    from uuid import UUID

    from syncr_api.habits.records import HabitRecord
    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.identifiers import AreaId, TaskId, TemplateEntryId
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


# The empty index: a caller that supplies none asks for orphan pins to carry no Area, which is
# what reading the arithmetic over literals does. Read-only, because a mutable module constant
# bound as a default argument would let one caller corrupt every future use process-wide.
NO_CONTENT_AREAS: Mapping[tuple[BindingKind, UUID], AreaId] = MappingProxyType({})


if TYPE_CHECKING:

    class AreaCarryingEntry(Protocol):
        """What the index reads off a template entry: which one it is, and whose it is."""

        @property
        def entry_id(self) -> TemplateEntryId: ...

        @property
        def kind(self) -> TemplateEntryKind: ...

        @property
        def area_id(self) -> AreaId: ...


def areas_of_content(
    *,
    tasks: Sequence[TaskRecord] = (),
    habits: Sequence[HabitRecord] = (),
    template_entries: Sequence[AreaCarryingEntry] = (),
) -> Mapping[tuple[BindingKind, UUID], AreaId]:
    """The Area each content entity carries, keyed the way an orphan pin looks its binding up.

    A task, a habit, and a concrete template entry each carry an Area of their own, which is what
    a pin left holding a binding the live plan no longer holds resolves its own Area from. The
    frame and an anchor carry none by the document's own rule, so they are absent rather than
    mapped: an orphaned pin over such content carries none, correctly.
    """
    return {
        **{(BindingKind.TASK, task.id): task.area_id for task in tasks},
        **{(BindingKind.HABIT, habit.id): habit.area_id for habit in habits},
        **{
            (BindingKind.TEMPLATE_ENTRY, entry.entry_id): entry.area_id
            for entry in template_entries
            if entry.kind is TemplateEntryKind.CONCRETE
        },
    }


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
    areas_of: Mapping[tuple[BindingKind, UUID], AreaId] = NO_CONTENT_AREAS,
) -> tuple[Placement, ...]:
    """Every committed block of one week, one per binding, in binding order.

    A pin replaces the live-plan block of the same binding, at the pin's own interval. A pin
    naming a binding the plan does not hold is a placement of its own: the user's edit outlives
    a re-solve that dropped the block, and its Area is its entity's, read through ``areas_of``.

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
            # Paired, the block's own Area stands: the pin moves the block, not whose it is.
            # Orphaned, the pin carries no Area and takes its binding entity's, so its minutes
            # stay committed time some Area figure sees.
            area_id=(
                placed.area_id
                if placed is not None
                else areas_of.get((pin.binding.kind, pin.binding.entity_id))
            ),
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
            (item for item in placed if item.immovable), span=_attributed_span
        )
        self._all_by_area = _by_area(placed, span=_area_span(self._now))
        self._immovable_by_area = _by_area(
            (item for item in placed if item.immovable), span=_worked_span
        )

    def immovable_minutes_of_task(self, task_id: TaskId) -> int:
        """Minutes of this task the solver is not offered again. The SOLVER's set.

        Membership is immovability and attribution decides how much of each member counts: taken
        over each placement's ATTRIBUTED span, clipped at ``now``, so only the part of the work
        that was actually done and has already been lived nets out of the offered remaining work.
        A confirmed skip attributes nothing and raises the figure by its minutes; an hour moved to
        a span ahead of ``now`` contributes nothing until it is lived, so the plan keeps offering
        it rather than ending the task over a pin it also holds.
        """
        placed = self._immovable_by_task.get(task_id)
        if placed is None:
            return 0
        return _minutes(_clipped_before(placed, self._now))

    def minutes_of_area(self, area_id: AreaId) -> int:
        """Minutes placed in this Area by any block, pinned or not, past or future.

        The probe's set, read through the figure's split at ``now``. Behind ``now`` the outcome log
        decides what counted, so a skipped hour stops crediting the reservation and the placed
        figure beside it alike; at or after ``now`` the placement's own span counts, because that
        is the part ``free`` subtracts, so the reservation gives back exactly the minutes free
        loses.
        """
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


def _attributed_span(placed: Placement) -> Iterable[Interval]:
    """The time this placement counts toward its content, which an outcome decides."""
    return () if placed.attributed is None else (placed.attributed,)


def _worked_span(placed: Placement) -> Iterable[Interval]:
    """The time this placement gave its Area inside the span it occupies.

    The attributed span narrowed to the placement's own interval, because an Area's floor is
    honoured by work the user did in time the plan holds. An outcome moving an hour to a span this
    placement does not cover honours no floor here, so the solver still owes those minutes, which is
    the direction a floor may safely be wrong in.
    """
    given = None if placed.attributed is None else placed.attributed.clipped_to(placed.interval)
    return () if given is None else (given,)


def _area_span(now: Instant) -> Callable[[Placement], Iterable[Interval]]:
    """What an Area's placed figure counts of one placement, split at ``now``.

    Built per index rather than taken as a bare strategy, because the split point is the reading:
    behind ``now``, the attribution table answers whether the work happened, so a skipped hour
    contributes nothing and cannot hold a reservation up; at or after ``now``, the placement's own
    span answers, because that is the part ``free`` subtracts and the reservation must lose exactly
    what free loses. A ``partial`` whose reported prefix ends before the block does leaves the
    unreported stretch between the two pieces to neither reading, which is the point: no outcome
    said it happened.
    """

    def read(placed: Placement) -> Iterable[Interval]:
        pieces = []
        if placed.attributed is not None and has_elapsed(placed.attributed, now):
            past = placed.attributed.clipped_to(Interval(placed.attributed.start, now))
            if past is not None:
                pieces.append(past)
        if not has_ended(placed.interval, now):
            future = placed.interval.clipped_to(Interval(now, placed.interval.end))
            if future is not None:
                pieces.append(future)
        return tuple(pieces)

    return read


def _placement_order(placed: Placement) -> tuple[Instant, Instant, str, str]:
    """A total order over placements: when, then what. Reproducible across two assemblies."""
    return (
        placed.interval.start,
        placed.interval.end,
        placed.binding.kind.value,
        f"{placed.binding.entity_id}\x1f{placed.binding.occurrence_key}",
    )


def _by_task(
    placed: Iterable[Placement], *, span: Callable[[Placement], Iterable[Interval]]
) -> Mapping[UUID, IntervalSet]:
    """The placements of each task, unioned. A chunk of a divided task is that task's.

    ``span`` is the caller's reading of a placement, injected rather than branched on, because the
    two readings exist for opposite reasons: the solver's figure counts time it cannot re-place
    and the probe's counts work that was done. A placement whose span reads as nothing under the
    caller's reading contributes nothing.
    """
    return _grouped(
        (item.binding.entity_id, interval)
        for item in placed
        if item.binding.kind is BindingKind.TASK
        for interval in span(item)
    )


def _by_area(
    placed: Iterable[Placement], *, span: Callable[[Placement], Iterable[Interval]]
) -> Mapping[UUID, IntervalSet]:
    """The placements of each Area, unioned. The frame and an anchor carry none.

    ``span`` is the caller's reading of a placement, injected for the same reason ``_by_task`` takes
    one: the Area's two figures ask opposite questions of one placement, and one asks what the
    outcome said happened behind ``now`` plus what the placement still holds ahead of it, while the
    other asks what the user gave the Area inside the span it occupies.
    """
    return _grouped(
        (item.area_id, interval)
        for item in placed
        if item.area_id is not None
        for interval in span(item)
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
