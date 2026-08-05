"""What one solve has decided so far: the blocks, the unfilled slots, and the refusals.

A solve is four phases over one accumulating value, and this is that value. It holds the blocks
placed, the state the thirteen rules judge a candidate against, the slots nothing could fill, and
the refusals the log keeps.

**The blocks and the state are appended together or not at all.** Three rules measure over what
the state holds -- H4 over the spans, H8 and H9 over an Area's minutes -- so a block added to the
document without its placement reaching the state would be invisible to all three, and the solve
would place work over time it had already taken.

## Everything ticket 38 needs is retained rather than recomputed

The refusals with their rule and window, the empty slots with their stated reason, and the
``bound`` clause each candidate carried are all kept here. Assembling a reason record is then a
projection of what the solve decided rather than a second derivation of it.

## The log is bounded by the inputs rather than by a chosen ceiling

Two rows per binding, which is exactly the clause budget's own figure for rejected windows, and
the bindings are the week's own content. So the log cannot grow with the number of windows tried,
and the bound needs no arbitrary total: it is the week's content times two.

## A divided task's chunk numbers are :mod:`syncr_solver.chunking`'s

They are decided in two halves at two moments, one as a piece is placed and one when the document is
built, and both live beside each other there rather than here: it is a distinct responsibility with
its own question, and holding it here put two of them in one file.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from syncr_domain.intervals import IntervalSet
from syncr_domain.plan import PlanDocument
from syncr_domain.reasons import CLAUSE_BUDGET, Blocked
from syncr_solver.chunking import numbered
from syncr_solver.figures import claimed_intervals, week_figures
from syncr_solver.ordering import block_key, slot_key
from syncr_solver.reading import demand_key
from syncr_solver.state import PartialPlan, Placement

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syncr_domain.gaps import EmptySlot
    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block
    from syncr_solver.constraints import BlockedCandidate
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.reading import DemandKey
    from syncr_solver.state import Sizing

# How many refused windows the log keeps per binding, read from the clause budget rather than
# restated: the record renders two per block, so a third row could never be read and would only
# grow a document that is appended forever. Derived rather than crossed by a test, so the two
# figures cannot be raised apart.
ROWS_PER_BINDING: Final = CLAUSE_BUDGET[Blocked]


@dataclass(frozen=True, slots=True, kw_only=True)
class Placed:
    """One block this attempt holds, with the placement the rules judged it at.

    The pair rather than the block alone, because a placement carries how much of a demand the
    block places and a block does not: the sizing is the solver's own choice, and H6 and H7 read
    it.

    ``chosen`` marks a placement THIS solve decided and may reconsider. It is false for everything
    that defines the space: the frame, an imported commitment, a buffer, a concrete entry, a block
    that has begun, and one the user pinned. The local search reads it, because a move over a
    placement nothing chose would be a move H10 or H11 refuses on every offer.
    """

    block: Block
    placement: Placement
    chosen: bool = False

    @classmethod
    def of(cls, block: Block, *, sizing: Sizing | None = None, chosen: bool = False) -> Placed:
        return cls(
            block=block,
            placement=Placement.of(block, sizing=sizing),
            chosen=chosen,
        )


@dataclass(frozen=True, slots=True)
class BlockedLog:
    """The refusals a solve keeps, bounded per binding.

    Construction's refusals only. A local-search move a rule refuses is a move not taken rather
    than a candidate the week could not hold, and recording one would tell the user a block was
    blocked from a window nothing ever asked to put it in.
    """

    rows: tuple[BlockedCandidate, ...] = ()

    def with_row(self, row: BlockedCandidate) -> BlockedLog:
        """This log plus one refusal, or this log unchanged because the binding is at its bound."""
        kept = sum(1 for held in self.rows if held.binding == row.binding)
        if kept >= ROWS_PER_BINDING:
            return self
        return BlockedLog((*self.rows, row))

    def with_rows(self, rows: Iterable[BlockedCandidate]) -> BlockedLog:
        log = self
        for row in rows:
            log = log.with_row(row)
        return log

    def refused(self) -> frozenset[BindingRef]:
        """Every binding this log holds a refusal for."""
        return frozenset(row.binding for row in self.rows)

    def honored_against(self, binding: BindingRef) -> tuple[str, ...]:
        """What refused this binding, in the words a shortfall names its honored constraints in."""
        return tuple(
            f"{row.rule.value}: {row.detail}" if row.detail else row.rule.value
            for row in self.rows
            if row.binding == binding
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Attempt:
    """One solve in progress: what it placed, what it could not, and the state it checks against.

    ``state`` is derived from ``placements`` rather than stated beside them, so the two cannot
    disagree about what the week holds.
    """

    inputs: SolveInputs
    placements: tuple[Placed, ...]
    state: PartialPlan
    slots: tuple[EmptySlot, ...] = ()
    log: BlockedLog = BlockedLog()

    @classmethod
    def of(
        cls,
        inputs: SolveInputs,
        *,
        placements: Sequence[Placed] = (),
        slots: Sequence[EmptySlot] = (),
        log: BlockedLog | None = None,
    ) -> Attempt:
        """An attempt holding exactly these placements, with the state rebuilt from them.

        The rebuild is what makes a local-search move expressible: a move replaces a placement
        rather than appending one, and the state has no removal.
        """
        return cls(
            inputs=inputs,
            placements=tuple(placements),
            state=PartialPlan.of(inputs, placed=[held.placement for held in placements]),
            slots=tuple(slots),
            log=BlockedLog() if log is None else log,
        )

    def adding(self, held: Placed) -> Attempt:
        """This attempt plus one placement, carried onto the state the next candidate is judged at.

        The state is extended rather than rebuilt, because appending is the construction's own
        shape and a rebuild per placement would re-sort every collection the week holds.
        """
        return replace(
            self,
            placements=(*self.placements, held),
            state=self.state.with_placed(held.placement),
        )

    def with_slot(self, slot: EmptySlot) -> Attempt:
        return replace(self, slots=(*self.slots, slot))

    def with_blocked(self, rows: Iterable[BlockedCandidate]) -> Attempt:
        return replace(self, log=self.log.with_rows(rows))

    def blocks(self) -> tuple[Block, ...]:
        """This attempt's blocks, with each division's numbers settled, in span order."""
        return tuple(sorted(numbered(self.placements), key=block_key))

    def document(self) -> PlanDocument:
        """The plan this attempt describes, with the three figures taken over it."""
        blocks = self.blocks()
        figures = week_figures(self.inputs, blocks)
        week = self.inputs.iso_week
        return PlanDocument(
            iso_week=week,
            zone_by_date={day: self.inputs.zone_by_date[day] for day in week.dates()},
            discretionary_minutes=figures.discretionary_minutes,
            unallocated_minutes=figures.unallocated_minutes,
            oversubscription_minutes=figures.oversubscription_minutes,
            blocks=blocks,
            forbidden_windows=self.state.forbidden_windows,
            empty_slots=tuple(sorted(self.slots, key=slot_key)),
            adjustments=tuple(adjustment.adjustment_id for adjustment in self.inputs.adjustments),
        )

    def placed_minutes(self) -> Mapping[DemandKey, int]:
        """Minutes placed toward each demand, less what the demand's own figure already nets.

        A task's chunks all count toward one demand and a habit's four occurrences are four separate
        demands, which is exactly the distinction :func:`~syncr_solver.reading.demand_key` states.

        **A placement the producer's figure already nets is not counted here.**
        ``EligibleTask.remaining_minutes`` arrives net of the immovable placements, which is a block
        that has begun and a pin, so counting their minutes again would subtract one hour twice and
        place a four-hour task at three. The set is read through the checker's own statement of it
        rather than restated, so this and H9 cannot come to net different sets.
        """
        found: dict[DemandKey, int] = {}
        for held in self.placements:
            if self.state.already_netted(held.placement.binding):
                continue
            key = demand_key(held.block.binding)
            found[key] = found.get(key, 0) + held.block.interval.total_minutes()
        return found

    def held_demands(self) -> frozenset[DemandKey]:
        """Every demand this attempt holds a block for, GROSS.

        The question an occurrence's eligibility asks, which is not the question a task's is: an
        occurrence is one block, so a pinned one is placed and its minutes are not a quantity
        anything subtracts. Netted the way :meth:`placed_minutes` is, a pinned occurrence would be
        offered a second window and H11 would refuse it there.
        """
        return frozenset(demand_key(held.block.binding) for held in self.placements)

    def spans_in(self, area_id: AreaId) -> IntervalSet:
        """The time this attempt's blocks cover in one Area, unioned so an overlap counts once."""
        return IntervalSet(
            held.block.interval for held in self.placements if held.block.area_id == area_id
        )

    def floor_shortfalls(self) -> Mapping[AreaId, int]:
        """Each Area's unmet floor, netting only what its own figure has not already netted.

        ``AreaBudget.floor_minutes`` arrives net of the immovable placements, which is a past block
        and a pin, so counting those again would let the solver place a floor short by whatever the
        previous solve had already done. The set is read through the checker's own statement of it
        rather than restated here.
        """
        already = IntervalSet(
            held.placement.interval
            for held in self.placements
            if self.state.already_netted(held.placement.binding)
        )
        return {
            area.area_id: max(0, area.floor_minutes - self._owed_against(area.area_id, already))
            for area in self.state.areas
        }

    def _owed_against(self, area_id: AreaId, already: IntervalSet) -> int:
        """Minutes this attempt places in one Area that its floor figure has not already netted."""
        return self.spans_in(area_id).subtract(already).total_minutes()

    def gaps(self) -> tuple[Interval, ...]:
        """The parts of the week still able to hold content, in span order.

        ``span.subtract(union(everything fixed and placed))``, taken through the denominator's own
        projection so the gaps a solve packs into and the figure a document reports for the same
        subtraction cannot disagree. A window scoped to named Areas is deliberately still here: it
        is capacity for every Area it does not name, and H13 is what refuses the ones it does.

        **Clipped to ``now``**, for the reason the probe clips its capacity there: nothing before
        that instant can hold new work, and crediting a solve with hours that have already gone
        would place this week's remaining work in the part of it that has already passed.
        """
        claimed = claimed_intervals([held.block for held in self.placements])
        return self.state.discretionary().subtract(claimed).after(self.inputs.now).members
