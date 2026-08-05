"""Producing a plan for a week that has none, and appending it as a revision.

One path from stored declarations to a stored plan: assemble the week, materialize it, append the
revision, bump the week's input version, and enqueue the projection that writes it to the calendar.
Two callers want that path and they differ in one field.

| Caller | Revision reason | Materialize cause |
|---|---|---|
| the plan horizon maintainer, bringing a week into range | ``horizon_advanced`` | ``checkpoint`` |
| the plan of last resort, after a solve fails terminally | ``materialized`` | ``solve_failed`` |

**The reason is what the history reads back**, so the two paths are two named entry points over one
core rather than one method with a flag: a week whose plan exists because time passed is a different
fact from a week whose plan exists because a solve could not.

**The version is bumped in the same transaction as the revision.** Appending a revision changes the
live plan, and the live plan is a solve input, so the version row -- the single serialization point
for anything that invalidates a running solve -- has to move. That is also what brings a week nobody
had touched into the tracked set: the row is created at version 1 on first reference, which a week
the maintainer plans is.

**The projection is enqueued, not performed.** The operations table is the queue, so what this
leaves behind is a pending ``projection`` operation for the week and the runner that drains it is
its own duty.

**A materialization records the weight set in force, and refuses when there is none.**
``PlanRevision.weight_set_version`` is not nullable and it is what a later comparison reads to say
which weights a plan was produced under. Materializing consults none -- there is nothing to weigh
when nothing is being chosen -- so recording the active version is the honest answer to "what was in
force", and inventing a version no row has would make that column a lie. Provisioning seeds every
tenant's version 1 inside the transaction that creates the tenant, so a tenant with no active weight
set is a corrupt tenant: it is refused loudly rather than planned around, and the horizon gauge and
its alert are what surface it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.plans.config import APPLIED
from syncr_api.plans.stored_documents import stored_document
from syncr_api.solving.config import MATERIALIZE, PROJECTION
from syncr_api.solving.outcomes import Succeeded
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.plan import RevisionReason
from syncr_solver import MaterializeCause, materialize

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.learned.repository import WeightSetRepository
    from syncr_api.plans.assembler import WeekAssembler
    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_domain.weeks import IsoWeek

# A materialization evaluates no objective, so there is no breakdown to store. Empty rather than
# absent, because the column is not nullable and a fabricated breakdown would be read as one a
# solve produced.
NO_OBJECTIVE: dict[str, object] = {}

# Which materialize cause belongs to which revision reason, stated once so the metric label and the
# stored reason cannot disagree about which path produced a week.
_CAUSE_BY_REASON = {
    RevisionReason.HORIZON_ADVANCED: MaterializeCause.CHECKPOINT,
    RevisionReason.MATERIALIZED: MaterializeCause.SOLVE_FAILED,
}

_log = get_logger("syncr.plans")


class NoWeightSetInForce(Exception):
    """A tenant with no active weight set, which provisioning makes impossible to create."""


@dataclass(frozen=True, slots=True)
class ProducedWeek:
    """What producing a week left behind: the revision, and the operation that did it."""

    revision: PlanRevisionRecord
    operation_id: object
    input_version: int


class WeekProducer:
    """Turns one tenant's declarations into a stored plan for one week."""

    def __init__(
        self,
        *,
        assembler: WeekAssembler,
        revisions: PlanRepository,
        versions: WeekInputVersionRepository,
        weights: WeightSetRepository,
        operations: OperationLifecycle,
    ) -> None:
        self._assembler = assembler
        self._revisions = revisions
        self._versions = versions
        self._weights = weights
        self._operations = operations

    async def advance_into(self, iso_week: IsoWeek, *, now: datetime) -> ProducedWeek:
        """Bring ``iso_week`` into range: a plan for a week nobody has touched.

        The reason is ``horizon_advanced``, so the history says the week was planned because time
        passed rather than because a solve could not produce one.
        """
        return await self._produced(iso_week, now=now, reason=RevisionReason.HORIZON_ADVANCED)

    async def materialize_week(self, iso_week: IsoWeek, *, now: datetime) -> ProducedWeek:
        """The plan of last resort: the frame, the commitments, the buffers, and the day's shape.

        The reason is ``materialized``, so the history distinguishes this from the maintainer's own
        path. Every Area slot is drawn unfilled, because nobody looked at the backlog: a degraded
        plan that explains itself beats an absent one, and the alternative on a week with no live
        revision is a blank grid and a calendar that runs out.
        """
        return await self._produced(iso_week, now=now, reason=RevisionReason.MATERIALIZED)

    @measured("week_producer")
    async def _produced(
        self, iso_week: IsoWeek, *, now: datetime, reason: RevisionReason
    ) -> ProducedWeek:
        weights = await self._weights.active()
        if weights is None:
            raise NoWeightSetInForce(
                "this tenant has no active weight set, so the weights a revision was produced "
                "under cannot be recorded. Provisioning seeds version 1 in the transaction that "
                "creates a tenant, so a tenant without one was not created by this application"
            )
        operation = await self._operations.enqueue(kind=MATERIALIZE, iso_week=iso_week)
        # Due now, which is what the coordinator's own `immediate` argument means: the maintainer
        # bypasses the debounce window, because nothing is being coalesced with anything.
        await self._operations.claim(operation.id)

        inputs = await self._assembler.assemble(iso_week, now)
        document = materialize(inputs, cause=_CAUSE_BY_REASON[reason])
        revision = await self._revisions.append(
            document=stored_document(document),
            objective_breakdown=NO_OBJECTIVE,
            status=APPLIED,
            reason=reason.value,
            weight_set_version=weights.version,
            input_version=inputs.input_version,
            created_at=now,
        )
        # The live plan changed, so the week's inputs did. Bumping here rather than leaving it to a
        # mutation is what makes a running solve's conditional write see the new plan, and it is
        # what creates the row for a week nothing had referenced.
        version = await self._versions.bump(iso_week, at=now)
        await self._operations.finish(operation.id, Succeeded(result_revision_id=revision.id))
        # The queue is the operations table, so this leaves a pending projection behind rather than
        # writing a calendar: the runner that drains it is its own duty.
        await self._operations.enqueue(kind=PROJECTION, iso_week=iso_week)
        _log.info(
            "plans.week.produced",
            iso_week=str(iso_week),
            reason=reason.value,
            revision_id=str(revision.id),
            operation_id=str(operation.id),
            input_version=version,
            blocks=len(document.blocks),
            empty_slots=len(document.empty_slots),
        )
        return ProducedWeek(revision=revision, operation_id=operation.id, input_version=version)
