"""What the solver may choose to place, and the demand each choice carries.

Two kinds of content bind late: a habit occurrence, whose cadence says it is due this week and
whose length the solver may size, and a task, whose remaining work the solver divides into
pieces. Everything else a week holds arrives at a span derivation determined, so it is the space
rather than a candidate inside it.

**One value serves both kinds**, because every reader asks the same four questions of a
candidate: what may sit in a window, how long it may be, what the ordering reads of it, and what
the block it becomes says about itself. A second type per kind would put the same branch in each
of those four readers.

## Which remaining-work quantity is read, and which is not

``remaining_minutes`` is ``EligibleTask.remaining_minutes``, the SOLVER's quantity: net of the
immovable placements only, so an unpinned block a previous solve placed is re-placed rather than
netted away. ``DeadlineDemand.remaining_minutes`` is the probe's, it nets every placement, and
read here it would schedule a task at half its size on every re-solve while both sides agreed
nothing was wrong.

## Why the floor shortfall is a field rather than a lookup

The ordering's first term is the unmet floor of the candidate's Area, and that figure moves as
content is placed, so a comparator that looked it up would need the week's state. Resolved onto
the candidate when a round's candidates are built, the comparator stays a total order over two
values and nothing else.

## A queue occurrence's content is chosen here, and the choice is the task ordering

A habit whose binding source is ``queue`` takes its cadence from itself and its content from the
backlog, so its content is the highest-ordered OPEN task in its own Area. The occurrence keeps its
own identity and its own length: what the backlog supplies is the NAME, so the block names the
chosen item rather than only the habit. An Area whose backlog holds nothing leaves the occurrence
with no content, so it is not eligible at all, and a slot that wanted it reports that its Area has
no eligible content.

**The draw reads every open task rather than the ones this round still has work for**, so the name
is a function of the inputs rather than of how far the packing has got: drawn from the round, an
occurrence would lose its content the moment the task it names was fully placed, and the same week
would bind three sessions and then stop.

**A queue habit's session is its own demand, and drawing a task does not net that task's minutes.**
The habit says "an hour of this Area, three times a week" and the task says how much work it needs,
and a user who declared both declared both, so a week holds the cadence AND the task's own
remaining work. Discharging the work instead is not this package's to do, for two reasons. The
figure such a discharge would reduce, ``EligibleTask.remaining_minutes``, arrives already netted,
so reducing it here is the re-netting ``inputs.py`` is shaped to prevent. And the assembler that
nets it cannot know WHICH task the draw will pick, so it would have to reserve the habit's minutes
against a task chosen by a rule of its own, which makes the choice the producer's rather than the
solver's. What the overlap costs is read by ``budget_deviation``, which compares the minutes an
Area receives against what it was budgeted and so charges them as far as they take that Area past
its target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingKind
from syncr_domain.reasons import Bound, PlacedSource
from syncr_solver.reading import demand_key
from syncr_solver.state import Sizing
from syncr_solver.tiebreak import in_tiebreak_order

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant
    from syncr_solver.inputs import EligibleTask, HabitOccurrence, SolveInputs
    from syncr_solver.reading import DemandKey

# What separates a habit's own name from the backlog item bound into it. The same separator the
# reason clauses already put between a determinant and its geometry.
_PART: Final = " · "


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """One demand the solver may place, and everything the ordering and the placer read.

    ``sizing`` describes the DEMAND rather than one piece of it, which is what H6 and H7 judge a
    piece against: a task's whole remaining minutes and the smallest piece it may be divided
    into, or an occurrence's smallest legal length.

    ``min_minutes`` and ``max_minutes`` bound ONE placement. For a task they are the smallest
    usable piece and what is left; for an occurrence they are its duration's own range, which the
    elastic rule chooses within.
    """

    binding: BindingRef
    area_id: AreaId
    title: str
    sizing: Sizing
    min_minutes: int
    max_minutes: int
    remaining_minutes: int
    deadline: Instant | None
    # Minutes of this demand the week owed before this expansion: a made-up occurrence, which is
    # exactly a cadence item that has fallen behind. The ordering's third term.
    stale_minutes: int
    # Whether this candidate is one of those made-up occurrences. Carried so the block it becomes
    # states it, which is what lets the outcome recorded against the block store the fact.
    make_up: bool = False
    # The unmet floor of this candidate's Area, as it stands in the round this candidate was built
    # for. The ordering's first term.
    floor_shortfall_minutes: int
    # The clause the block carries, built here so the reason record is a projection of what the
    # solver chose rather than a reconstruction of it.
    bound: Bound

    @property
    def sizes_within_a_range(self) -> bool:
        """Whether the elastic rule chooses this candidate's length rather than the packer.

        True for a habit occurrence and false for a task. An occurrence's range is a declaration
        about one session, so the largest length that fits without passing the Area's own figures
        is the rule; a task's range is what is left of it, and taking the largest that fits is
        just packing.
        """
        return self.binding.kind is BindingKind.HABIT


def candidates_for(
    inputs: SolveInputs,
    *,
    placed_minutes: Mapping[DemandKey, int],
    held_demands: frozenset[DemandKey] = frozenset(),
    floor_shortfalls: Mapping[AreaId, int],
) -> tuple[Candidate, ...]:
    """Every demand still to place, in tie-break order.

    ``placed_minutes`` is what this attempt has already placed per demand, NET of what the demand's
    own figure already nets, which is the figure a task's remaining work is compared against.
    ``held_demands`` is every demand the plan holds a block for, GROSS, which is what an
    occurrence's eligibility asks.

    **The two questions cannot share one figure.** A task's demand arrives net of the pins, so
    counting a pinned piece's minutes again would place a four-hour task at three; an occurrence's
    demand is the occurrence itself, so NOT counting a pinned one offers it a second window and has
    H11 refuse it there. Measured on the reference week: two refusals and one Gym session offered
    twice.

    ``floor_shortfalls`` is each Area's unmet floor as the round found it.

    The tasks are ordered first and the occurrences after them, because a queue occurrence's
    content is the highest-ordered open task in its Area and that ordering is the same one, taken
    over every open task rather than over the ones this round still has work for.
    """
    tasks = _task_candidates(inputs.eligible_tasks, placed_minutes, floor_shortfalls)
    occurrences = _occurrence_candidates(
        inputs.habit_occurrences,
        held_demands,
        floor_shortfalls,
        backlog=_task_candidates(inputs.eligible_tasks, {}, floor_shortfalls),
    )
    return in_tiebreak_order((*tasks, *occurrences))


def _task_candidates(
    tasks: Sequence[EligibleTask],
    placed_minutes: Mapping[DemandKey, int],
    floor_shortfalls: Mapping[AreaId, int],
) -> tuple[Candidate, ...]:
    """One candidate per task with work left, in tie-break order.

    A task placed to its remaining minutes is not a candidate: there is nothing left of it, and
    offering one would let the packer place work the demand does not claim.
    """
    found = []
    for task in tasks:
        left = task.remaining_minutes - placed_minutes.get(demand_key(task.binding), 0)
        if left <= 0:
            continue
        found.append(
            Candidate(
                binding=task.binding,
                area_id=task.area_id,
                title=task.title,
                sizing=Sizing(
                    whole_minutes=left,
                    min_chunk_minutes=task.min_chunk_minutes,
                    splittable=task.splittable,
                ),
                min_minutes=task.min_chunk_minutes if task.splittable else left,
                max_minutes=left,
                remaining_minutes=left,
                deadline=task.deadline,
                stale_minutes=0,
                floor_shortfall_minutes=floor_shortfalls.get(task.area_id, 0),
                # The placement was the search's own choice, so the clause names the placed arm
                # rather than ``queue``: a queue habit occurrence that draws this same task keeps
                # ``BindingSource.QUEUE``, and the two cases stay two words on the wire.
                bound=Bound(source=PlacedSource.SOLVER, selected=task.title),
            )
        )
    return in_tiebreak_order(tuple(found))


def _occurrence_candidates(
    occurrences: Sequence[HabitOccurrence],
    held_demands: frozenset[DemandKey],
    floor_shortfalls: Mapping[AreaId, int],
    *,
    backlog: Sequence[Candidate],
) -> tuple[Candidate, ...]:
    """One candidate per due occurrence the plan does not hold yet.

    An occurrence is one block, so an occurrence the plan holds anywhere is done. It is not
    divided and it is not placed twice: the cadence says how many occurrences the week owes, and
    each of them is its own candidate with its own identity.
    """
    found = []
    for occurrence in occurrences:
        if demand_key(occurrence.binding) in held_demands:
            continue
        content = _content_of(occurrence, backlog)
        if content is None:
            continue
        title, bound = content
        found.append(
            Candidate(
                binding=occurrence.binding,
                area_id=occurrence.area_id,
                title=title,
                sizing=Sizing(
                    whole_minutes=occurrence.duration.min_minutes,
                    min_chunk_minutes=occurrence.duration.min_minutes,
                    splittable=False,
                ),
                min_minutes=occurrence.duration.min_minutes,
                max_minutes=occurrence.duration.max_minutes,
                remaining_minutes=occurrence.duration.min_minutes,
                deadline=None,
                stale_minutes=occurrence.duration.min_minutes if occurrence.is_debt else 0,
                make_up=occurrence.is_debt,
                floor_shortfall_minutes=floor_shortfalls.get(occurrence.area_id, 0),
                bound=bound,
            )
        )
    return tuple(found)


def _content_of(
    occurrence: HabitOccurrence, backlog: Sequence[Candidate]
) -> tuple[str, Bound] | None:
    """What this occurrence holds and what its block says it was bound by, or nothing.

    Nothing for a ``queue`` occurrence whose Area's backlog is empty: the cadence is due and
    there is no content for it, which is the one state an occurrence can be in that leaves it
    unplaceable rather than merely unplaced.

    The cursor a rotation advanced is not carried on ``SolveInputs`` and the variant it resolved
    to is, so the clause names the variant. Every label in this package is derived from the
    resolved inputs and from nothing else.
    """
    if occurrence.binding_source is BindingSource.ROTATION:
        selected = occurrence.variant or occurrence.title
        return (
            _PART.join((occurrence.title, selected)),
            Bound(source=BindingSource.ROTATION, selected=selected, cursor=selected),
        )
    if occurrence.binding_source is BindingSource.QUEUE:
        drawn = next((item for item in backlog if item.area_id == occurrence.area_id), None)
        if drawn is None:
            return None
        return (
            _PART.join((occurrence.title, drawn.title)),
            Bound(source=BindingSource.QUEUE, selected=drawn.title),
        )
    return (
        occurrence.title,
        Bound(source=BindingSource.FIXED, selected=occurrence.title),
    )
