"""How the assembler acquires what a week already holds: the live plan, and its pins.

The netting rules every quantity on a solve input obeys are stated over PLACEMENTS: a task's
remaining work nets the immovable ones, an Area's floor reservation nets all of them, and a
deadline's demand nets those falling before it. So the assembler needs one answer to "what is
already committed in this week", and this is the seam it asks.

It is a protocol for the same reason the budget report's occupancy reader and the habit
outcome log's reader are: the concern that stores these rows owns its own storage, and an
assembly should acquire that answer rather than reach into another module's table.

``NoPlacements`` answers with nothing, and that is the correct reading of this deployment
rather than a placeholder for one. All three parts of the answer need the same missing
capability, which is why they are one seam and not three:

*The live plan.* ``plan_revisions`` stores a document as JSONB and nothing yet reads its
interior. A revision's blocks carry a binding, an interval, and an Area, and no code names the
keys a stored block holds, so no revision in this deployment can be read back as placements.

*The pins.* ``pins`` exists and carries a ``binding`` column, and nothing writes one: there is
no pin write path yet, and the interior of a stored ``BindingRef`` is undefined for the same
reason. A read of the table could not attribute a row to the task or Area it pins.

*The outcomes.* ``block_outcomes`` is written and readable, so this half could be answered
today. It is not, because an outcome only changes what a PLACEMENT attributes: with no live
plan there is no placement to attribute, so supplying the rows alone would change no figure.
Whoever supplies the live plan supplies these in the same read.

So the honest answer today is that no week holds a placement: every task's remaining work is
its corrected estimate less recorded minutes, every Area's two floor quantities are equal, and
every demand is gross. Each of those is what is true while nothing is placed.

The seam earns its keep in the suite rather than in the production wiring. Without it, the two
netting rules could only ever be asserted against an empty week; with it, the assembler's tests
supply real placements and assert both quantities through the real arithmetic.

Whoever brings the plan document's interior online supplies a reader over ``plan_revisions``
and ``pins`` and changes one line in ``injection.py``. What that reader owes this module is
stated on the protocol below, and the one rule it must not break is that a pinned block and its
live-plan block are ONE placement: counted twice, a pinned hour would net twice out of every
quantity that reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syncr_domain.outcomes import RecordedOutcome
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek
    from syncr_solver.inputs import Pin


@dataclass(frozen=True, slots=True)
class WeekPlacements:
    """The plan of record for one week, the pins bound to it, and what happened to its blocks.

    Three fields rather than one flattened placement list, because each is read for reasons of
    its own as well as netted together: the document is what the churn term is measured against,
    the pins are hard constraints the solver may not move, and the outcomes say how many of a
    past block's minutes count toward the content it holds. Which placement set each netting rule
    counts is the assembler's own statement, in one place, over all three.
    """

    live_plan: PlanDocument | None = None
    pins: tuple[Pin, ...] = ()
    outcomes: tuple[RecordedOutcome, ...] = ()


class WeekPlacementReader(Protocol):
    """What an assembly asks for the capacity a week has already committed."""

    async def read(self, iso_week: IsoWeek) -> WeekPlacements:
        """The live plan of ``iso_week``, its pins, and the outcomes recorded on it. Writes nothing.

        **The live plan is the plan of record, not a pending proposal.** A proposal nobody
        has approved has committed no capacity, so netting against one would report work as
        already placed on the strength of a plan the user may reject.

        **A pin and the live-plan block it pins are one placement.** A pin names a binding
        the document also holds, so a reader returning both leaves the assembler to pair
        them by binding; the pin's interval is where the block is, because that is what a pin
        means. Returning a pin for a binding the document does not hold is legitimate: the
        user's edit outlives a re-solve that dropped the block.

        **At most one outcome per binding.** An outcome says what happened to one content
        instance in this week, and two rows for one binding would attribute it twice. The
        write path holds that by keying a row on the block, whose id is a digest of the week
        and the binding; a reader composing rows some other way owes the same property.
        An outcome for a binding the document does not hold is legitimate and attributes
        nothing: the row is retained because it is a fact about a week that happened.

        The order of none of the three collections is part of the contract. Every quantity
        derived from them is a minute count or an interval union, and neither depends on the
        order it was taken in.
        """
        ...


class NoPlacements:
    """The placements of a deployment where no block can be read back from a document.

    Reads nothing and writes nothing. A week assembled against it holds no committed
    capacity, which is what is true while nothing names the keys a stored binding holds.
    """

    async def read(self, iso_week: IsoWeek) -> WeekPlacements:
        return WeekPlacements()
