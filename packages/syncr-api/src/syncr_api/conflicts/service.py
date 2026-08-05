"""``ConflictService``: read the conflicts a tenant holds, and record how one was answered.

A conflict is the only condition in this product that pushes a notification, and the one thing this
service may not do is act on the user's behalf before they answer. So every path here starts from an
answer the user chose, and each of the three answers does something different:

| The answer | What it changes |
|---|---|
| ``moved`` | frees the block to be re-placed, bumps the week's version, and requests a solve |
| ``kept-both`` | **records the answer and nothing else.** No bump, no solve, no plan change |
| ``retyped`` | changes what the commitment reserves around itself, bumps, and requests a solve |

``kept-both`` is the one mutating path in this product that bumps no input version, and that is not
an oversight: it changes neither the solve inputs nor the live plan. The overlap stays, and the
detector never raises it again.

## What ``moved`` does depends on who can move the block

That discrimination is :mod:`syncr_api.conflicts.overlapped`, and the third of its three answers is
the one worth stating here: a block whose time a declaration fixes is **not moved and not recorded
as answered**. The request is refused, naming what fixed the block, because there are two ways to
change such a placement -- an exception for this week, or a change to the shape -- and one is a
one-off while the other is structural. Choosing for the user is what this product does not do.

## Nothing is relocated by this service, ever

Not even for the case where a solve will relocate something. The block is freed by removing what
held it, and the solver decides where it goes on the next pass, which arrives as an ordinary
proposal for the user to look at. That is why the ``moved`` path needs no notion of a window a block
is now ineligible for: the commitment that raised the conflict is hard occupancy the solver may not
place anything inside, and a buffer it cast is a block the solver may not overlap, so the window is
already closed to the block by the rules the solve is subject to.

## A resolution joins a solve rather than rivalling one

The version bump is what invalidates a solve already running, and the request either joins the
non-terminal operation for the week or creates one. The debounce and the coalescing belong to the
solve coordinator; what this service owes is that an answer never leaves the week without a pass
that reads it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.anchors.declarations import TypeAssignment
from syncr_api.conflicts.config import ANCHOR_TYPE_FIELD, CONFLICT_RESOURCE
from syncr_api.conflicts.overlapped import Movability, overlapped_block
from syncr_api.conflicts.views import Resolved
from syncr_api.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from syncr_api.core.patches import Absent
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.plans.config import KEPT_BOTH_RESOLUTION, MOVED_RESOLUTION
from syncr_api.plans.stored_documents import plan_document
from syncr_api.solving.config import SOLVE
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.anchors.service import AnchorService
    from syncr_api.conflicts.declarations import ChosenResolution
    from syncr_api.conflicts.pins import PinRelease
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.plans.conflicts import PlanConflictRepository
    from syncr_api.plans.records import ConflictRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository
    from syncr_domain.identifiers import ConflictId
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.conflicts")


class ConflictService:
    """Reads one tenant's conflicts, and records the answer to one."""

    def __init__(
        self,
        *,
        conflicts: PlanConflictRepository,
        revisions: PlanRepository,
        versions: WeekInputVersionRepository,
        operations: OperationRepository,
        lifecycle: OperationLifecycle,
        anchors: AnchorService,
        pins: PinRelease,
        clock: Clock,
    ) -> None:
        self._conflicts = conflicts
        self._revisions = revisions
        self._versions = versions
        self._operations = operations
        self._lifecycle = lifecycle
        self._anchors = anchors
        self._pins = pins
        self._clock = clock

    @measured("conflicts")
    async def list_all(
        self, principal: Principal, *, resolved: bool | None
    ) -> tuple[ConflictRecord, ...]:
        """The conflicts this tenant holds, earliest overlap first. Writes nothing.

        ``resolved=False`` is what the banner reads. The resolved ones are retained rather than
        deleted, so asking for them is a legitimate read rather than a leak of dead rows.
        """
        require_scope(principal, Scope.PLAN_READ)
        return await self._conflicts.list_all(resolved=resolved)

    @measured("conflicts")
    async def resolve(
        self, principal: Principal, conflict_id: ConflictId, chosen: ChosenResolution
    ) -> Resolved:
        """Record how this conflict was answered, and do what that answer names.

        Answers with the resolved conflict and the solve that will read it, which is ``None`` for
        the one answer that asks for no solve.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        found = await self._found(principal, conflict_id)
        _require_an_unanswered_conflict(found)
        await self._acted_on(principal, found, chosen)
        recorded = await self._conflicts.resolve(
            found.id, resolution=chosen.resolution, at=self._clock()
        )
        if recorded is None:
            raise Conflict(
                "That conflict was answered by another request while this one was being applied, "
                "so this answer was not recorded. Read it again to see the answer that was."
            )
        _log.info(
            "conflicts.conflict.resolved",
            tenant_id=str(principal.tenant_id),
            conflict_id=str(found.id),
            iso_week=str(found.iso_week),
            anchor_id=str(found.anchor_id),
            resolution=chosen.resolution,
        )
        return Resolved(recorded, operation=await self._solve_for(found, chosen))

    async def _acted_on(
        self, principal: Principal, found: ConflictRecord, chosen: ChosenResolution
    ) -> None:
        """Do what this answer names, before the answer is recorded.

        Nothing is done for ``kept-both``: the overlap stays, and the answer itself is the whole
        change. The other two each free something, and both are refused rather than half applied.
        """
        if chosen.resolution == KEPT_BOTH_RESOLUTION:
            _require_no_type_for(chosen)
            return
        if chosen.resolution == MOVED_RESOLUTION:
            _require_no_type_for(chosen)
            await self._freed(found)
            return
        await self._retyped(principal, found, chosen)

    async def _freed(self, found: ConflictRecord) -> None:
        """Free the block this conflict names, or refuse because nothing may move it.

        The live plan is read here rather than passed in, because who can move a block is a fact
        about the plan as it stands now: a later revision may have relocated it, and a pin may have
        been released since the conflict was raised.
        """
        overlapped = overlapped_block(await self._live(found.iso_week), found.block_id)
        if overlapped.movable_by is Movability.NOBODY:
            raise Conflict(
                "Nothing was moved. This block's time is fixed by something you declared rather "
                "than chosen by the solver, and there are two ways to change that: pin this "
                "occurrence somewhere else to make this week an exception, or change what puts it "
                "there. syncr does not choose between them, because one is a one-off and the "
                f"other is structural. The block is a {overlapped.origin} block."
            )
        if overlapped.movable_by is Movability.THE_USER:
            await self._pins.release(found.iso_week, found.binding)

    async def _retyped(
        self, principal: Principal, found: ConflictRecord, chosen: ChosenResolution
    ) -> None:
        """Change what the commitment reserves around itself, which regenerates what it casts.

        The retype persists on the commitment's series, which is what the anchor service does with
        one: a type is a statement about the meeting rather than about this occurrence of it.
        """
        if isinstance(chosen.anchor_type, Absent):
            raise ValidationFailed(
                "Retyping states which of your commitment types to apply, and this request stated "
                "none, so nothing was changed. Send the type to apply, or null to leave the "
                "commitment as opaque busy time.",
                errors=[
                    FieldError(
                        field=ANCHOR_TYPE_FIELD,
                        message="a retype states a type, or null for none of them",
                    )
                ],
            )
        try:
            await self._anchors.retype(
                principal, found.anchor_id, TypeAssignment(anchor_type_id=chosen.anchor_type)
            )
        except NotFound as absent:
            raise Conflict(
                "That commitment is no longer on your calendar, so there is no type to change and "
                "nothing was changed. The overlap it raised is gone with it: answer this conflict "
                "as kept-both to close it."
            ) from absent

    async def _solve_for(
        self, found: ConflictRecord, chosen: ChosenResolution
    ) -> OperationRecord | None:
        """Bump the week and ask for a pass that reads the answer, unless nothing changed.

        ``kept-both`` bumps no version and requests no solve, which is what makes it the one
        mutating path in this product that leaves the solve inputs and the live plan alone.
        """
        if chosen.resolution == KEPT_BOTH_RESOLUTION:
            return None
        await self._versions.bump(found.iso_week, at=self._clock())
        in_flight = await self._operations.in_flight(found.iso_week, kind=SOLVE)
        if in_flight is not None:
            return in_flight
        return await self._lifecycle.enqueue(kind=SOLVE, iso_week=found.iso_week)

    async def _live(self, iso_week: IsoWeek) -> PlanDocument | None:
        """The week's live plan, or ``None`` when it holds none."""
        latest = await self._revisions.latest(iso_week)
        return None if latest is None else plan_document(latest.document)

    async def _found(self, principal: Principal, conflict_id: ConflictId) -> ConflictRecord:
        found = await self._conflicts.find(conflict_id)
        if found is None:
            raise NotFound(f"No {CONFLICT_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=CONFLICT_RESOURCE)
        return found


def _require_an_unanswered_conflict(found: ConflictRecord) -> None:
    """A conflict is answered once. The record of the answer is permanent."""
    if not found.is_resolved:
        return
    raise Conflict(
        f"That conflict was already answered as {found.resolution}, and an answer is a permanent "
        "record rather than a setting. Nothing was changed. If the overlap is still there, the "
        "collision will be raised again the next time it is detected."
    )


def _require_no_type_for(chosen: ChosenResolution) -> None:
    """A commitment type is named only by the answer that changes one."""
    if isinstance(chosen.anchor_type, Absent):
        return
    raise ValidationFailed(
        f"A {chosen.resolution} answer changes no commitment type, so naming one would have been "
        "ignored. Nothing was changed: send the answer without it, or retype instead.",
        errors=[
            FieldError(
                field=ANCHOR_TYPE_FIELD,
                message="only a retyped answer states a type",
            )
        ],
    )
