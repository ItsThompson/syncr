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

The candidate then rides on the operation, which is the only object that crosses from the request to
the worker, and the worker folds it in as an argument to the assembly. Nothing is written to the
concession table, which WA2 requires and a test asserts.

**A tradeoff request never joins a pending solve.** A pin made two seconds earlier would absorb it
and the concession would silently vanish from a proposal the user is then asked to approve. So a
pending solve for the week is superseded first, which is the state machine's own
``pending``-to-``superseded`` edge, and the replacement is created after the row it replaces is
closed.

**A solve already RUNNING is refused rather than displaced.** The single-flight invariant is the
database's: at most one non-terminal solve per week exists, so there is no second row to create
while one runs. Waiting for it inside the request would hold a connection for up to two seconds,
and joining it is the one thing this route may not do. The coordinator owns the queued
alternative, and until it ships the honest answer is a conflict naming what still works.

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
from syncr_api.solving.config import PENDING, SOLVE
from syncr_api.solving.outcomes import Superseded
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
    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_api.plans.tradeoffs import Offer
    from syncr_api.plans.verdicts import WeekProbe
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository
    from syncr_api.user_settings.solve_inputs import WeekInputVersions
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.concessions")


class ConcessionService:
    """One tenant's tradeoff requests, and the concessions their approvals left behind."""

    def __init__(
        self,
        *,
        assembler: WeekAssembler,
        probe: WeekProbe,
        adjustments: WeekAdjustmentRepository,
        operations: OperationRepository,
        lifecycle: OperationLifecycle,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._assembler = assembler
        self._probe = probe
        self._adjustments = adjustments
        self._operations = operations
        self._lifecycle = lifecycle
        self._versions = versions
        self._clock = clock

    @measured("concessions")
    async def request(
        self, principal: Principal, iso_week: str, requested: RequestedConcession
    ) -> OperationRecord:
        """Solve ``iso_week`` again against the requested concession, and persist nothing.

        Returns the operation to follow. The concession itself becomes real only if the user
        approves the proposal it produces.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        offer = await self._offered(week, requested)

        await self._make_room_for(week)
        operation = await self._lifecycle.enqueue(
            kind=SOLVE,
            iso_week=week,
            candidate_adjustment=as_document(offer.as_candidate(adjustment_id=uuid4())),
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
        if await self._operations.in_flight(week, kind=SOLVE) is None:
            await self._lifecycle.enqueue(kind=SOLVE, iso_week=week)

    async def _offered(self, week: IsoWeek, requested: RequestedConcession) -> Offer:
        """The offer the enumerator made for what was requested, or a 422 naming what it can be.

        A request for a concession syncr did not offer is refused rather than honoured, because the
        offer is where the figures come from: the nights a reduction may touch, and how much of a
        floor is left to breach.
        """
        inputs = await self._assembler.assemble(week, self._clock())
        offered = self._probe.offered_verdict_for(inputs)
        offer = offered.offered((requested.kind, requested.target_id))
        if offer is None:
            raise ValidationFailed(
                f"That concession is not one {week} is offered. Nothing was changed, and the "
                "week still holds whatever concessions it held.",
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

    async def _make_room_for(self, week: IsoWeek) -> None:
        """Make room for this request's own solve, or refuse to displace a running one.

        A pending solve is closed, because a request carrying a candidate may not join one: a pin
        made two seconds earlier would absorb the concession and the proposal would look as though
        syncr ignored it. The single-flight invariant is enforced by a partial unique index, so
        this is what makes the insert that follows legal rather than a race the database catches.
        """
        in_flight = await self._operations.in_flight(week, kind=SOLVE)
        if in_flight is None:
            return
        if in_flight.status != PENDING:
            raise Conflict(
                "A solve of that week is already running, so a tradeoff cannot be evaluated yet. "
                "Nothing was changed: the week keeps its plan and its concessions, and this "
                "request can be made again once the solve lands."
            )
        await self._lifecycle.finish(in_flight.id, Superseded())
