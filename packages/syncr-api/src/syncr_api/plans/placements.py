"""How the assembler acquires what a week already holds: the live plan, its pins, and its outcomes.

The netting rules every quantity on a solve input obeys are stated over PLACEMENTS: a task's
remaining work nets the immovable ones, an Area's floor reservation nets all of them, and a
deadline's demand nets those falling before it. So the assembler needs one answer to "what is
already committed in this week", and this is the seam it asks.

It is a protocol for the same reason the budget report's occupancy reader and the habit
outcome log's reader are: the concern that stores these rows owns its own storage, and an
assembly should acquire that answer rather than reach into another module's table.

## What one call costs, which the assembly's own read figure does not say

``StoredPlacements`` performs FOUR statements per call, and the assembler counts the seam as one
collaborator read. The two figures answer different questions and both are true; what matters is
that the p95 budgets in section 19 are calibrated against a collaborator count, and this is the
collaborator whose count and whose statement count differ most. Recalibrating those budgets against
measured statements is ticket 1253's, and stating the gap here is not doing it.

## A pin stops constraining its week once the week has reached the placement it names

One rule, and it is read in two places: this module refuses to carry such a pin into an assembly,
and the pin route refuses to create one. Both read :func:`constrains_a_solve`, so neither can drift
from the other.

What it settles, and each was open before a pin route existed:

**A pin on a block that has already begun.** ``syncr_solver.immovability`` documents the
started-block rule winning for that input -- the block stays where it ran, and the pin yields --
while ``inheritance._placed`` seeds a pinned block at the pin unconditionally, which would move it.
The two disagreed because the input was unreachable. It stays unreachable: the route refuses the
drag, and a pin whose interval the week has since reached is not carried, so the block reaches the
checker with no pin against it and stays where it ran, exactly as that module's own prose says.

**A pin whose interval elapses while its block lives only in a pending proposal.** Carried, the
solver builds a block for pinned content the live plan does not hold, the guard reads that block as
a past the live plan does not state, and every solve of that week fails from then on. Not carried,
the producer never emits the block and nothing reaches the guard.

What it costs is the pin's own hold on an elapsed span, and the no-overlap rule already protects
that span from being placed into. The RECORD is untouched: the row stays until something releases
it, and the edit event beside it is permanent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syncr_api.plans.stored_documents import plan_document
from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.intervals import has_started
from syncr_solver.inputs import Pin

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.plans.pins import PinRepository
    from syncr_api.plans.reality import BlockOutcomeRepository
    from syncr_api.plans.records import PinRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.user_settings.repository import SettingsRepository
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.outcomes import RecordedOutcome
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek


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

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekPlacements:
        """The live plan of ``iso_week``, its pins, and the outcomes recorded on it. Writes nothing.

        ``span`` is the week's own elapsed span, which the assembler has already resolved against
        the zone profile. It is a parameter for the reason the budget report's occupancy reader
        takes one: an outcome is keyed by the instant its block was scheduled at, so the rows of a
        week are the rows inside its span, and re-deriving that span here would resolve the zone
        profile a second time and could answer with a different one.

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


class StoredPlacements:
    """What a week holds, read from the three tables that hold it.

    Four statements: the newest revision, the week's pins, the outcomes of the span, and the profile
    whose home zone a pin's creation instant is dated in. The last is what makes the pin's own
    ``pinned_on`` the date the USER made the edit rather than the UTC date it landed on, which are
    different dates for anything after early evening in the zones this product is used in.
    """

    def __init__(
        self,
        revisions: PlanRepository,
        pins: PinRepository,
        outcomes: BlockOutcomeRepository,
        settings: SettingsRepository,
    ) -> None:
        self._revisions = revisions
        self._pins = pins
        self._outcomes = outcomes
        self._settings = settings

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekPlacements:
        latest = await self._revisions.latest(iso_week)
        home_zone = (await self._settings.read()).home_zone
        return WeekPlacements(
            live_plan=None if latest is None else plan_document(latest.document),
            pins=tuple(
                _as_pin(record, home_zone=home_zone)
                for record in await self._pins.for_week(iso_week)
            ),
            outcomes=tuple(record.as_domain() for record in await self._outcomes.for_span(span)),
        )


def constrains_a_solve(interval: Interval, now: Instant) -> bool:
    """Whether a pin at ``interval`` is still a constraint on the week's solve.

    A pin the week has reached is a record and not a constraint. There is nothing left for the
    solver to honour, because the moment has passed and the placement is a fact, and carrying one is
    what makes the two rules that protect the past disagree about it.

    Read by this module, which drops such a pin from an assembly, and by the pin route, which
    refuses to create one. One predicate, so the created set and the honoured set are the same set.
    """
    return not has_started(interval, now)


def constraining(pins: Sequence[Pin], *, now: Instant) -> tuple[Pin, ...]:
    """The pins an assembly stamped at ``now`` carries: those whose placement it has not reached."""
    return tuple(pin for pin in pins if constrains_a_solve(pin.interval, now))


def _as_pin(record: PinRecord, *, home_zone: str) -> Pin:
    """One stored pin as the value the solver seeds a placement from.

    ``pinned_on`` is derived rather than stored, because the row holds the instant and a date needs
    a zone. The home zone is the one this product resolves a date in when no week is in question,
    which is the same reading the Week screen's own empty state takes.
    """
    return Pin(
        binding=record.binding,
        interval=record.interval,
        pinned_on=local_date(record.created_at, home_zone),
        superseded_placement=record.superseded_placement,
        objective_delta=record.objective_delta,
    )
