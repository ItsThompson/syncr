"""Pinning a block, releasing a pin, and rejecting one proposed move. Three acts, one mechanism.

## The pin transaction, and the ordering the arithmetic forces

```
pin(week, blockId, start)
  ├── read the plan the solver last produced: the pending proposal, or the plan of record
  ├── refuse a placement the week has already reached, in either direction
  ├── ONE TRANSACTION
  │     ├── weights.active()                          or refuse: a pin cannot be priced
  │     ├── read the deadline, the Area's floor, the pins held
  │     ├── assembler.assemble(week, now)             PRE-PIN frame, before any write
  │     ├── refuse a placement outside the assembled span
  │     ├── pinPrice(produced, block, accepted)       the delta, measured in that frame
  │     ├── weekVersion.bump()                     -> the version the response reports
  │     ├── pins.hold(blockId, accepted, superseded)  the row, priced in that frame
  │     ├── assembler.assemble(week, now)             POST-PIN frame. Reads the pin back
  │     ├── probe(post-pin inputs)                    provenance = probe
  │     ├── verdicts.record(week, verdict)            only if it TRANSITIONED
  │     ├── editEvents.append(...)                    E1: the pair, or neither
  │     └── coordinator.request_solve(week, version, session_mode_active)
  └── { pin, verdict, operation }
```

**Two assemblies, and each serves one consumer.** The price and the feature snapshot describe the
state the proposal was made in, so both read the frame taken BEFORE the pin row exists: the terms
that read ``eligible_tasks`` and ``placed_toward`` net a pinned binding, so a cost measured against
a frame that already counts the pin is a difference between two different questions. The verdict
describes the state the pin left the week in, so it is computed in the frame taken AFTER. Passing
the pin to the assembler as an argument instead would mean restating "one pin per binding" inside
the assembler for the week that already holds one, and the table already states that.

**The version is bumped between the two frames**, so the verdict names the input state the pin
produced. A verdict carries the version it was computed against, and a client reasons optimistically
with it: a verdict computed in the pre-pin frame would answer with the version the week held before
this edit, which is the one state the response is certainly not about.

``tests/test_pin_write_path.py`` drives one request and holds the order above, the consumer each
frame serves, and the count of observations the two histograms take.

**``E1``: the edit event is written in the same transaction as the pin.** A pin without its event is
a training label with no features, and the features are a fact about an instant that has passed, so
the loss is unrecoverable. Nothing between the two writes can commit one without the other.

**The verdict transition is written in the same transaction too**, and only when the verdict is a
transition. So a burst of twelve drags writes at most one row, and a pin cannot commit without the
transition it caused: the row feeds a product metric whose data is unrecoverable after the fact.
The release path records none, because it computes no verdict; the transition its solve produces is
recorded on the commit path, and the one time passing produces is the maintainer's.

## Rejecting a proposed move is pinning the block where it already is

Rejecting a proposed move is pinning the block where it already is. It needs no mechanism of its
own: the rejection resolves the accepted interval from the plan of record and then takes exactly the
path above. So the pairwise preference falls out
-- the solver proposed there, the user chose here -- and there is no rejection record, no rejection
column, and no second code path that could disagree with this one.

The proposal is not cleared. The version bump invalidates it and the solve this request asks for
replaces the slot with whatever it proposes next, which is correct rather than lazy: once the
rejected block is pinned, a different arrangement of the rest may be better.

## What a pin may not be

A pin is a training label, so it is refused wherever it would be a preference nobody expressed.
A placement the week has reached is refused in both directions: the block that has begun, because
the moment has passed and the solver could not honour a pin on it anyway, and a requested start
already gone, because nothing can be scheduled into it. A placement outside the week it names is
refused because a pin binds one week.

Creating one as a convenience is refused by the absence of any path to it: nothing here pins a block
the caller did not name, and the drag rules that keep a jittery pointer from naming one are the Week
screen's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.concessions.config import ISO_WEEK_FIELD
from syncr_api.core.errors import Conflict, NotFound
from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.learned.weight_reading import as_weight_set
from syncr_api.pins.config import PIN_RESOURCE
from syncr_api.pins.costs import pin_price
from syncr_api.pins.features import edit_context
from syncr_api.pins.pre_edit import resolve_pre_edit
from syncr_api.pins.request_shape import (
    _block_of,
    _require_a_placement_inside_the_week,
    _require_a_placement_the_week_has_not_reached,
    _starting_at,
)
from syncr_api.plans.declarations import EditToRecord, PinToHold
from syncr_api.plans.production import NoWeightSetInForce
from syncr_api.plans.stored_documents import plan_document
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.learned.repository import WeightSetRepository
    from syncr_api.pins.declarations import BlockRejected, PinRequested
    from syncr_api.plans.assembler import WeekAssembler
    from syncr_api.plans.edits import EditEventRepository
    from syncr_api.plans.pins import PinRepository
    from syncr_api.plans.proposals import PendingProposalRepository
    from syncr_api.plans.recording import VerdictRecorder
    from syncr_api.plans.records import PinRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.verdicts import WeekProbe
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_api.solving.records import OperationRecord
    from syncr_api.tasks.repository import TaskRepository
    from syncr_domain.feasibility import Verdict
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.pins")


@dataclass(frozen=True, slots=True, kw_only=True)
class PinnedWeek:
    """What one edit answers with: the pin, the live verdict, and the solve to follow.

    Three values because a client redraws all three at once: the block at its new time with the pin
    glyph, the verdict strip, and whatever it uses to know when the unpinned remainder has reflowed.
    The verdict is computed synchronously and needs no solve to complete, which is what makes the
    redraw possible at all.
    """

    pin: PinRecord
    verdict: Verdict
    operation: OperationRecord


class PinService:
    """One tenant's pins: made, released, and made by refusing a proposed move."""

    def __init__(
        self,
        *,
        assembler: WeekAssembler,
        probe: WeekProbe,
        revisions: PlanRepository,
        proposals: PendingProposalRepository,
        pins: PinRepository,
        edits: EditEventRepository,
        verdicts: VerdictRecorder,
        versions: WeekInputVersionRepository,
        weights: WeightSetRepository,
        coordinator: SolveCoordinator,
        tasks: TaskRepository,
        areas: AreaRepository,
        clock: Clock,
        session_mode_active: bool = False,
    ) -> None:
        self._assembler = assembler
        self._probe = probe
        self._revisions = revisions
        self._proposals = proposals
        self._pins = pins
        self._edits = edits
        self._verdicts = verdicts
        self._versions = versions
        self._weights = weights
        self._coordinator = coordinator
        self._tasks = tasks
        self._areas = areas
        self._clock = clock
        # What this request stated about the weekly session. The recorder above is bound to the
        # same answer at composition; this copy is for the release path, which computes no verdict
        # of its own but schedules the solve whose recorder reads it.
        self._session_mode_active = session_mode_active

    @measured("pins")
    async def pin(self, principal: Principal, iso_week: str, requested: PinRequested) -> PinnedWeek:
        """Put one block where the user dragged it, and answer with the verdict that follows."""
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        produced = await self._last_produced(week)
        block = _block_of(produced, requested.block_id)
        accepted = _starting_at(requested.start, block)
        now = self._clock()
        _require_a_placement_the_week_has_not_reached(block, accepted, now)
        return await self._held(week, produced, block, accepted, now=now)

    @measured("pins")
    async def reject(
        self, principal: Principal, iso_week: str, rejected: BlockRejected
    ) -> PinnedWeek:
        """Refuse one proposed move by pinning the block at the placement it already has."""
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        proposed = await self._proposed(week)
        block = _block_of(proposed, rejected.block_id)
        existing = await self._existing(week, block)
        # No started-block check: the plan of record's placement is inherently valid to keep.
        return await self._held(week, proposed, block, existing, now=self._clock())

    @measured("pins")
    async def unpin(self, principal: Principal, iso_week: str, pin_id: UUID) -> None:
        """Release one pin, so the next solve may place its content wherever it fits.

        The row goes and the edit event stays, which is what the resolution table means by the
        removed pin's record being retained as training data: the event carries the pair, the price
        and the weight-set version, so nothing the learning layer reads is lost with the constraint.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        found = await self._pins.find(pin_id)
        if found is None or found.iso_week != week:
            raise NotFound(f"No {PIN_RESOURCE} of that week matches that identifier.")
        # Defense in depth rather than the check producing that 404: `find` is scoped to this
        # principal's own tenant, so another tenant's identifier already read as absent above.
        authorize_tenant(principal, found.tenant_id, resource=PIN_RESOURCE)

        await self._pins.release(pin_id)
        version = await self._versions.bump(week, at=self._clock())
        _log.info(
            "pins.pin.released",
            tenant_id=str(principal.tenant_id),
            iso_week=str(week),
            pin_id=str(pin_id),
            input_version=version,
        )
        await self._coordinator.request_solve(
            week, version, session_mode_active=self._session_mode_active
        )

    async def _held(
        self,
        week: IsoWeek,
        produced: PlanDocument,
        block: Block,
        accepted: Interval,
        *,
        now: datetime,
    ) -> PinnedWeek:
        """The one transaction every edit performs, whichever route asked for it.

        TWO assemblies, deliberately, and the module docstring states which consumer each serves.

        The first assembly runs BEFORE `pins.hold`; the second runs AFTER. End to end this path
        measured 18.6 ms on a 1-block week, 27.4 ms on a 24-block week and 39.1 ms on an 84-block
        week, warm, against a local database on one developer machine. That is a shape rather than a
        p95: nothing here measures a production pool, and no reading of it has been taken since.
        """
        stored = await self._weights.active()
        if stored is None:
            raise NoWeightSetInForce(
                "this tenant has no active weight set, so a pin could not be priced under one. "
                "Provisioning seeds version 1 in the transaction that creates a tenant, so a "
                "tenant without one was not created by this application"
            )

        # Pre-edit state, resolved BEFORE the pin enters the assembly.
        pre_edit = await resolve_pre_edit(
            block,
            week,
            tasks=self._tasks,
            areas=self._areas,
            pins=self._pins,
        )

        # PRE-PIN ASSEMBLY: the frame the price and the context are measured in.
        pre_pin_inputs = await self._assembler.assemble(week, now)
        _require_a_placement_inside_the_week(accepted, pre_pin_inputs.span)
        weights = as_weight_set(stored)
        price = pin_price(produced, block, accepted, inputs=pre_pin_inputs, weights=weights)

        version = await self._versions.bump(week, at=now)
        record = await self._pins.hold(
            PinToHold(
                iso_week=week,
                block_id=block.id,
                binding=block.binding,
                interval=accepted,
                superseded_placement=block.interval,
                objective_delta=price.objective_delta,
                weight_set_version=stored.version,
                created_at=now,
            )
        )

        # POST-PIN ASSEMBLY: the frame the verdict is computed in. It reads the pin row back
        # complete: one statement wrote it, so no reader inside this transaction can observe a pin
        # without its cost.
        post_pin_inputs = await self._assembler.assemble(week, now)
        verdict = self._probe.verdict_for(post_pin_inputs)
        transition = await self._verdicts.record(week, verdict)
        event = await self._edits.append(
            EditToRecord(
                iso_week=week,
                binding=block.binding,
                proposed=block.interval,
                accepted=accepted,
                objective_delta=price.objective_delta,
                weight_set_version=stored.version,
                context=edit_context(
                    inputs=pre_pin_inputs,
                    document=produced,
                    block=block,
                    accepted=accepted,
                    breakdown=price.breakdown,
                    measurement_delta=price.measurement_delta,
                    task_deadline=pre_edit.task_deadline,
                    area_floor_declared=pre_edit.area_floor_declared,
                    pinned_blocks_before=pre_edit.pinned_blocks_before,
                ),
                created_at=now,
            )
        )
        _log.info(
            "pins.pin.held",
            iso_week=str(week),
            pin_id=str(record.id),
            edit_event_id=str(event),
            block_id=block.id,
            input_version=version,
            objective_delta=price.objective_delta,
            weight_set_version=stored.version,
            moved=block.interval != accepted,
            feasible=verdict.feasible,
            shortfalls=len(verdict.shortfalls),
            verdict_event_id=None if transition is None else str(transition.id),
        )
        return PinnedWeek(
            pin=record,
            verdict=verdict,
            operation=await self._coordinator.request_solve(
                week, version, session_mode_active=self._session_mode_active
            ),
        )

    async def _last_produced(self, week: IsoWeek) -> PlanDocument:
        """The plan the solver last produced for this week: the pending slot, or the plan of record.

        The slot outranks the revision because a pin's counterfactual is what the SOLVER chose, and
        a proposal awaiting assent is the most recent thing it chose. Dragging a block a proposal
        would move therefore records the preference against the placement the user is looking at,
        rather than against one an earlier revision holds and the screen no longer shows.
        """
        pending = await self._proposals.find(week)
        if pending is not None:
            return plan_document(pending.document)
        latest = await self._revisions.latest(week)
        if latest is None:
            raise Conflict(
                f"{week} holds no plan yet, so there is no block to pin. Nothing was changed: ask "
                "for a solve of the week, and pin what it produces."
            )
        return plan_document(latest.document)

    async def _proposed(self, week: IsoWeek) -> PlanDocument:
        """The pending proposal, which is what a rejection is a rejection OF."""
        pending = await self._proposals.find(week)
        if pending is None:
            raise Conflict(
                f"{week} has no proposal awaiting your assent, so there is no proposed move to "
                "reject. Nothing was changed."
            )
        return plan_document(pending.document)

    async def _existing(self, week: IsoWeek, block: Block) -> Interval:
        """Where the plan of record holds this block, which is what a rejection pins it at.

        A proposal that ADDS a block proposes no move, so there is no existing placement to keep it
        at and the rejection is refused rather than turned into a pin at the proposed interval:
        pinning there would record the user preferring exactly what they refused.
        """
        latest = await self._revisions.latest(week)
        stored = None if latest is None else plan_document(latest.document)
        held = None if stored is None else stored.blocks_by_id().get(block.id)
        if held is None:
            raise Conflict(
                f"that proposed change to {week} adds {block.title} rather than moving it, so "
                "there is no existing placement to keep it at. Nothing was changed: approve the "
                "proposal, or drag the block where you want it."
            )
        return held.interval
