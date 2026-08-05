"""One reading of a week the seven objective terms share, so no two of them derive it twice.

Every term is a fraction of something the week holds, and three of those denominators are
already stated elsewhere in this package: the discretionary set H9 measures free capacity over,
the claimed spans the document's own ``unallocated_minutes`` subtracts, and the set of bindings
the assembler had already netted before its figures arrived. Each is read through its existing
statement rather than restated here, because a second statement of a quantity is how the figure
a document reports comes to disagree with the figure a term charges.

## The one thing this module states for the first time

Which local hour an instant falls in. A fitted time-of-day curve is keyed on the hour of the
user's own day and a skip probability on the part of that day, so both need the zone active on
the date the block starts in. The day bounds come from
:func:`~syncr_domain.weeks.local_days` through the checker's state, which is the one derivation
of what a local date spans; this reads the zone of the date that owns the instant and nothing
else.

**A block starting before the week's first local day opens reads in the first date's zone.** It
is reachable only where that date opens after the span does, which is a travel move of more than
a day of offset, and the alternative is refusing a placement over a rendering detail of a
fitted curve. Which date owns an instant is the mapping's statement, and this reads it forward.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind
from syncr_domain.intervals import IntervalSet
from syncr_domain.plan import PlanError
from syncr_domain.zones import resolve_zone
from syncr_solver.figures import claimed_intervals
from syncr_solver.state import PartialPlan

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.zones import ZoneId
    from syncr_solver.inputs import SolveInputs

# A binding without its occurrence or its chunk: what a task's demand and the blocks placed
# toward it are paired on. `BindingRef.content_key` keeps the chunk index, and a split task's
# chunks all belong to the one demand, so the pairing has to drop it.
type ContentKey = tuple[BindingKind, UUID]


def content_key(binding: BindingRef) -> ContentKey:
    """The content a binding names, without which instance or chunk of it this is."""
    return (binding.kind, binding.entity_id)


type DemandKey = tuple[BindingKind, UUID, str]
"""One demand the solver places: content, and which instance of it, without the chunk.

**Not the same key as** :data:`ContentKey`, and the difference is one component. A task's chunks all
belong to one demand, so both keys drop the chunk number; a habit's four occurrences in one week are
four SEPARATE demands, each with its own identity and its own block, so this one keeps the
occurrence. Read as content, three of the four would look already placed the moment the first one
landed.
"""


def demand_key(binding: BindingRef) -> DemandKey:
    """The demand this binding belongs to: everything but which chunk of it this is."""
    return (binding.kind, binding.entity_id, binding.occurrence_key)


@dataclass(frozen=True, slots=True)
class Placed:
    """One block the plan places into an Area, with that Area non-optional.

    The pair exists so no term has to re-ask whether a block carries an Area. Three of them read
    only the blocks that do, and asking once here removes the same filter from each of them along
    with the branch a type checker would otherwise need to narrow ``area_id`` at every use.
    """

    block: Block
    area_id: AreaId

    def minutes(self) -> int:
        return self.block.interval.total_minutes()


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanReading:
    """One week, one plan, and the three sets every term is a fraction of.

    Built once per evaluation. The terms take this rather than the plan and the inputs
    separately, so each one reads the same discretionary set, the same free time, and the same
    netted bindings as the hard-constraint checker does.
    """

    plan: PlanDocument
    inputs: SolveInputs
    # The checker's own reading of the week: what H9 measures against, and the one statement of
    # which bindings the assembler's figures already net.
    state: PartialPlan
    # The parts of the week an Area may claim, before any of it is placed. The denominator three
    # terms are a fraction of.
    discretionary: IntervalSet
    # Discretionary time no block carrying an Area covers. The set the document's own
    # `unallocated_minutes` totals, which a test in this package crosses.
    free: IntervalSet
    # Each local date's opening instant with the zone it opened in, ascending. Read by the hour
    # lookup and by nothing else. Both halves come from ``inputs.zone_by_date``: the bounds through
    # the checker's own ``local_days``, and the zone from the same mapping, so one question has one
    # source. The document carries its own copy of that mapping and it is deliberately unread, since
    # taking the bounds from one and the zone from the other is how the two come to disagree.
    days: tuple[tuple[Instant, ZoneId], ...]

    @classmethod
    def of(cls, plan: PlanDocument, *, inputs: SolveInputs) -> PlanReading:
        """Read ``plan`` against the week ``inputs`` describes.

        The week guard is here rather than only on ``evaluate``, so both entry points agree. This
        one is public and the suite calls it directly, and a cross-week pair would otherwise build
        a reading whose day list describes one week and whose blocks belong to another.
        """
        require_one_week(plan, inputs)
        state = PartialPlan.of(inputs)
        discretionary = state.discretionary()
        return cls(
            plan=plan,
            inputs=inputs,
            state=state,
            discretionary=discretionary,
            free=discretionary.subtract(claimed_intervals(plan.blocks)),
            days=tuple((day.interval.start, inputs.zone_by_date[day.on]) for day in state.days),
        )

    def discretionary_minutes(self) -> int:
        """The week's denominator. Zero for a week with nothing an Area could claim."""
        return self.discretionary.total_minutes()

    def area_blocks(self) -> tuple[Placed, ...]:
        """The blocks that carry an Area, paired with it, in the order the document holds them.

        An Area is what makes a block a claim on discretionary time, so it is also what makes a
        block something an objective term has anything to say about. The frame and an imported
        commitment carry none: one defines how much time exists and the other is time the
        product does not own, and no choice was made about either.
        """
        return tuple(
            Placed(block=block, area_id=block.area_id)
            for block in self.plan.blocks
            if block.area_id is not None
        )

    def minutes_in(self, area_id: AreaId) -> int:
        """Minutes this plan's blocks cover in one Area, unioned so an overlap counts once.

        GROSS, net of nothing, which is what makes it comparable with ``target_minutes``. Two
        blocks of one Area over one hour occupy one hour of the week, and an allocation may not
        be satisfied by time that does not exist.
        """
        return IntervalSet(
            block.interval for block in self.plan.blocks if block.area_id == area_id
        ).total_minutes()

    def placed_toward(self, binding: BindingRef, *, before: Instant | None = None) -> int:
        """Minutes this plan places toward one demand, counting only what its figure has not.

        NET of the bindings :meth:`~syncr_solver.state.PartialPlan.already_netted` names, because
        the demand this is compared against is: ``EligibleTask.remaining_minutes`` arrives with
        the started blocks and the pins already subtracted, so counting their minutes here would
        credit one placement to both sides of one comparison. That is the fault ticket 29 found
        at four sites and ticket 33 at a fifth, and the netting is read from the checker's state
        rather than restated so the two cannot drift.

        ``before`` clips to a deadline, which is why the union is taken before the total: a block
        straddling the instant contributes the part that lands in time.
        """
        wanted = content_key(binding)
        spans = IntervalSet(
            block.interval
            for block in self.plan.blocks
            if content_key(block.binding) == wanted and not self.state.already_netted(block.binding)
        )
        return (spans if before is None else spans.before(before)).total_minutes()

    def chunks_toward(self, binding: BindingRef) -> tuple[int, ...]:
        """How long each piece this plan places toward one demand is, longest first.

        The same netted set as :meth:`placed_toward`, and for the same reason: the ideal chunk a
        piece is measured against is capped by what the demand still owes, and that figure
        arrives net of the started blocks and the pins.
        """
        wanted = content_key(binding)
        return tuple(
            sorted(
                (
                    block.interval.total_minutes()
                    for block in self.plan.blocks
                    if content_key(block.binding) == wanted
                    and not self.state.already_netted(block.binding)
                ),
                reverse=True,
            )
        )

    def local_hour(self, at: Instant) -> int:
        """The hour of the user's own day this instant falls in, from 0 to 23."""
        return at.astimezone(resolve_zone(self._zone_at(at))).hour

    def _zone_at(self, at: Instant) -> ZoneId:
        """The zone active on the local date that owns this instant.

        The dates are ascending, so the date that owns an instant is the last one to open at or
        before it.

        **The day list is never empty, and that is derived rather than guarded.** A date is dropped
        only when its own midnight falls at or after the next date's, which needs the offset to fall
        by a whole day; the range of offsets is 28 hours end to end, so at most one such fall can
        happen in a week and never seven. A guard here would be one with no reachable violation.
        """
        opens = [start for start, _ in self.days]
        found = bisect_right(opens, at) - 1
        return self.days[max(found, 0)][1]


def shortest_placeable_minutes(inputs: SolveInputs) -> int:
    """The smallest piece any content this week holds could be placed in.

    The inventory of what may occupy a gap rather than a threshold chosen here: a task's declared
    minimum chunk, and an occurrence's smallest legal length. A week with no such content has
    nothing that could use a gap, so no gap it leaves is unusable and the figure is zero.
    """
    return min(
        (
            *(task.min_chunk_minutes for task in inputs.eligible_tasks),
            *(occurrence.duration.min_minutes for occurrence in inputs.habit_occurrences),
        ),
        default=0,
    )


def gap_minutes(earlier: Placed, later: Placed) -> int:
    """Unoccupied minutes between two placements, and zero where they abut or overlap.

    Zero rather than a negative, because the callers ask how much room the schedule leaves
    between two placements and an overlap leaves none. A user-authored overlap is a legitimate
    content of a week, so this is a reachable state rather than a fault.
    """
    if later.block.interval.start <= earlier.block.interval.end:
        return 0
    return int((later.block.interval.start - earlier.block.interval.end).total_seconds() // 60)


def in_start_order(placed: Sequence[Placed]) -> tuple[Placed, ...]:
    """These placements as the day runs, ending in an identity so no two of them tie.

    The identity is what makes the order total, exactly as the document's own block order and the
    solver's tie-breaking do: without it two blocks equal on span would be ordered by whatever their
    inputs happened to do, and the pairs a term charges would change with an input's arrival order
    while no placement changed. Measured, on a plan holding one such tie: 0.125 against 0.250 for
    two orders of the same three blocks.
    """
    return tuple(
        sorted(
            placed,
            key=lambda one: (one.block.interval.start, one.block.interval.end, one.block.id),
        )
    )


def require_one_week(plan: PlanDocument, inputs: SolveInputs) -> None:
    """A document and the inputs it is read against describe one week.

    Every figure the terms compare is resolved for a specific week: an Area's target, a task's
    remaining minutes, the discretionary denominator, and the local dates the hour lookup reads.
    Read against another week's inputs the answer would be arithmetic over unrelated quantities
    rather than an error, which is the failure this product cannot detect any other way.
    """
    if plan.iso_week != inputs.iso_week:
        raise PlanError(
            f"a plan for {plan.iso_week} cannot be scored against inputs for {inputs.iso_week}: "
            "every figure the terms compare is resolved for one specific week"
        )
