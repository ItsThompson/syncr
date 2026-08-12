"""Requesting a concession, reading the ones a week holds, and revoking one.

Three acts on one week, and the split between the first and the last two is the whole design of
this feature: **requesting persists nothing, and only approving does.** Without that split,
approval would append a revision that breaches an unchanged input and the next solve would propose
putting everything back, so the concession would be undone by the mechanism meant to honor it.

## Requesting

A request names a kind and a target, and the figures come from the enumeration rather than from the
caller. That is what keeps a client from asking to reduce a routine below its own floor, to breach a
floor by more than it reserves, or to concede anything at all on a week that is not short: the
service assembles the week, probes it, enumerates what could close each gap, and requires the
requested concession to be one syncr actually offered.

That probe is a verdict, so the transition it finds is recorded in the request's own transaction,
under the ``tradeoff`` surface. Nothing else about the request persists, which is the point below,
and the transition is not an exception to it: a row saying the week was found impossible is a fact
about the week rather than a concession the user has agreed to.

The candidate then rides on the operation, which is the only object that crosses from the request to
the worker, and the worker folds it in as an argument to the assembly. Nothing is written to the
concession table, which WA2 requires and a test asserts.

**A tradeoff request never joins a solve already in flight.** A pin made two seconds earlier would
absorb it and the concession would silently vanish from a proposal the user is then asked to
approve. So the week's in-flight solve is superseded first, which is the state machine's own edge
from ``pending`` and from ``running`` alike, and the replacement is created after the row it
replaces is closed. The interleaving that makes superseding a RUNNING solve safe is the
coordinator's, and its module states it: the running worker's write is one transaction whose last
statement is its own terminal step, so it either lands whole or rolls back whole.

**A week holding nothing a solve placed is refused, before a solve is asked for.** A concession is
an agreement to give something up, and on such a week there is nothing the product chose to give up:
the candidate would fill empty space, so the authority rule would auto-apply it and the concession
would become the plan of record with no row saying it had been conceded. The refusal is here rather
than in the classifier, which knows nothing about concessions and must not learn. **It is the one
conflict this module produces**, and the only route that can answer it is the tradeoff request.

## Revoking

Removing a concession changes the inputs, so WA8's two effects are one transaction here: the row
goes and the week's input version is bumped, which makes any solve in flight fail its conditional
write. A re-solve is then requested, unless one is already in flight, because the version bump is
the signal the running one reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.concessions.config import CONCESSION_RESOURCE, ISO_WEEK_FIELD
from syncr_api.core.errors import Conflict, NotFound, ValidationFailed
from syncr_api.core.errors import FieldError as WireFieldError
from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.plans.candidates import as_document
from syncr_api.plans.solved import holds_a_solver_placed_block
from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from uuid import UUID

    from syncr_api.concessions.declarations import RequestedConcession
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.plans.adjustments import WeekAdjustmentRepository
    from syncr_api.plans.assembler import WeekAssembler
    from syncr_api.plans.recording import VerdictRecorder
    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_api.plans.tradeoffs import Offer
    from syncr_api.plans.verdicts import WeekProbe
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_api.solving.records import OperationRecord
    from syncr_api.user_settings.solve_inputs import WeekInputVersions
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek
    from syncr_solver.inputs import SolveInputs

_log = get_logger("syncr.concessions")


class ConcessionService:
    """One tenant's tradeoff requests, and the concessions their approvals left behind."""

    def __init__(
        self,
        *,
        assembler: WeekAssembler,
        probe: WeekProbe,
        adjustments: WeekAdjustmentRepository,
        verdicts: VerdictRecorder,
        coordinator: SolveCoordinator,
        current: WeekInputVersionRepository,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._assembler = assembler
        self._probe = probe
        self._adjustments = adjustments
        self._verdicts = verdicts
        self._coordinator = coordinator
        self._current = current
        self._versions = versions
        self._clock = clock

    @measured("concessions")
    async def request(
        self, principal: Principal, iso_week: str, requested: RequestedConcession
    ) -> OperationRecord:
        """Solve ``iso_week`` again against the requested concession, and persist nothing.

        Returns the operation to follow. The concession itself becomes real only if the user
        approves the proposal it produces.

        A request carrying a candidate never joins an existing operation, which is the coordinator's
        rule: a pin made two seconds earlier would otherwise absorb it and the proposal would look
        as though syncr had ignored the concession. A solve already running is superseded for the
        same reason, so the answer is an operation to follow rather than a refusal.

        A week whose plan holds nothing a solve placed is refused before the solve is asked for, so
        no operation exists for a request that could not have been honoured.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        inputs = await self._assembler.assemble(week, self._clock())
        _require_a_solve_to_concede_against(week, inputs.live_plan)
        offer = await self._offered(inputs, requested)

        operation = await self._coordinator.request_solve(
            week,
            await self._current_version(week),
            immediate=True,
            candidate=as_document(offer.as_candidate(adjustment_id=uuid4())),
        )
        _log.info(
            "concessions.tradeoff.requested",
            tenant_id=str(principal.tenant_id),
            iso_week=str(week),
            kind=requested.kind,
            operation_id=str(operation.id),
            recovers_minutes=offer.recovers,
        )
        return operation

    @measured("concessions")
    async def approved(self, principal: Principal, iso_week: str) -> list[WeekAdjustmentRecord]:
        """The concessions ``iso_week`` holds, so a week that absorbed one does not read as easy."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._adjustments.for_week(require_an_iso_week(iso_week, field=ISO_WEEK_FIELD))

    @measured("concessions")
    async def revoke(self, principal: Principal, iso_week: str, adjustment_id: UUID) -> None:
        """Remove one concession, invalidate the week, and ask for a plan without it."""
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        # Before either table is touched. `hold` states the rule: whoever takes this row takes it
        # first, and a caller that writes another table before it deadlocks with one that does not.
        # It orders the two transactions rather than merging them. An approval waiting here commits
        # afterwards and re-creates the concession it was solved under, and a week with no version
        # row is not locked at all.
        await self._current.hold(week)
        found = await self._adjustments.find(adjustment_id)
        if found is None or found.iso_week != week:
            raise NotFound(f"No {CONCESSION_RESOURCE} of that week matches that identifier.")
        # Defense in depth rather than the check producing that 404: `find` is scoped to this
        # principal's own tenant, so another tenant's identifier already read as absent above.
        authorize_tenant(principal, found.tenant_id, resource=CONCESSION_RESOURCE)

        await self._adjustments.remove(adjustment_id)
        # WA8: removing a concession changes the inputs, so the version moves before anything is
        # asked to solve. A solve already running then fails its conditional write and its
        # follow-up reads the week without this concession.
        await self._versions.bump(WeekRange(first=week, last=week))
        _log.info(
            "concessions.concession.revoked",
            tenant_id=str(principal.tenant_id),
            iso_week=str(week),
            adjustment_id=str(adjustment_id),
            kind=found.kind,
        )
        await self._coordinator.request_solve(week, await self._current_version(week))

    async def _current_version(self, week: IsoWeek) -> int:
        """The version this week now holds, for the coordinator's answer to the caller.

        Not the guard, which is the conditional write's comparison against the version the worker
        stamps when it loads the inputs. What it is for is the client: the operation the caller
        follows names the input state its own request was acknowledged at.
        """
        return await self._current.tracked_version(week)

    async def _offered(self, inputs: SolveInputs, requested: RequestedConcession) -> Offer:
        """The offer the enumerator made for what was requested, or a 422 naming what it can be.

        A request for a concession syncr did not offer is refused rather than honoured, because the
        offer is where the figures come from: the nights a reduction may touch, and how much of a
        floor is left to breach.

        The week is the assembly's own rather than a second argument, because these inputs were
        assembled for it and two arguments no type can hold together would let a caller pass one
        week's figures under another week's name.
        """
        offered = self._probe.offered_verdict_for(inputs)
        # Recorded beside the probe that found it, in the request's own transaction. A request that
        # is then refused rolls the row back with everything else, and the transition it saw is
        # written by the next mutation or by the maintainer's next tick, at most fifteen minutes
        # later: the same answer the design gives for a transition a read observes.
        await self._verdicts.record(inputs.iso_week, offered.verdict)
        offer = offered.offered((requested.kind, requested.target_id))
        if offer is None:
            raise ValidationFailed(
                f"That concession is not one {inputs.iso_week} is offered. Nothing was changed, "
                "and the week still holds whatever concessions it held.",
                errors=[
                    WireFieldError(
                        field="targetId",
                        message=(
                            f"no {requested.kind} concession is offered for that target this "
                            "week: read the week's verdict for the ones that are"
                        ),
                    )
                ],
            )
        return offer


def _require_a_solve_to_concede_against(week: IsoWeek, live: PlanDocument | None) -> None:
    """A week holding nothing a solve placed has nothing to concede against, so this refuses.

    Raised before the solve is requested, so a request that cannot be honoured leaves no operation
    for a caller to follow and nothing for the worker to adopt. The statement names solving the week
    rather than the classification the refusal is derived from: what the reader has to do is get a
    plan that chose something, and the vocabulary the product decides that with is not theirs.
    """
    if holds_a_solver_placed_block(live):
        return
    raise Conflict(
        f"{week} holds no block a solve placed, so there is no solve to concede against. Nothing "
        "was changed: solve the week first, and concede against the plan it produces."
    )
