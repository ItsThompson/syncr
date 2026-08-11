"""The frozen views the plan repositories return.

A repository hands back one of these rather than a mapped row, for the reason every
repository in this application does: a mapped row carries a session, a load state, and
setters, so returning one would let a caller change a stored value outside the method that
owns the write. These carry values only.

That is why the JSONB payloads are copied out of the row rather than aliased, and why the
copy is DEEP: a plan document holds a list of blocks, so a top-level copy would still hand
back the row's own list, and ``record.document["blocks"].append(...)`` would change the
value the row holds. Nothing is persisted either way, because a plain JSONB column emits no
``UPDATE`` for a mutated value, so what the copy buys is that the record cannot be used to
reach the row it was read from.

``iso_week`` is an :class:`~syncr_domain.weeks.IsoWeek` here and a string in the column.
The conversion happens at this boundary, so no caller parses a week identifier and no
caller formats one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.outcomes import RecordedOutcome

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.columns import JsonObject
    from syncr_api.plans.config import (
        AdjustmentKind,
        ConflictResolution,
        RevisionReason,
        RevisionStatus,
    )
    from syncr_api.plans.surfaces import VerdictSurface
    from syncr_domain.feasibility import Provenance, ShortfallKind
    from syncr_domain.identifiers import (
        AnchorId,
        BlockOutcomeId,
        ConflictId,
        OperationId,
        PinId,
        PlanRevisionId,
        TenantId,
        VerdictEventId,
    )
    from syncr_domain.identity import BindingRef, BlockId
    from syncr_domain.intervals import Interval
    from syncr_domain.outcomes import OutcomeState
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True)
class PlanRevisionRecord:
    """One appended revision, exactly as it was stored."""

    id: PlanRevisionId
    tenant_id: TenantId
    iso_week: IsoWeek
    status: RevisionStatus
    reason: RevisionReason
    document: JsonObject
    objective_breakdown: JsonObject
    weight_set_version: int
    input_version: int
    supersedes_id: PlanRevisionId | None
    created_at: datetime
    approved_at: datetime | None

    def is_approved(self) -> bool:
        """Whether the user assented to this revision."""
        return self.approved_at is not None


@dataclass(frozen=True, slots=True)
class PendingProposalRecord:
    """The one proposal awaiting assent for a week."""

    tenant_id: TenantId
    iso_week: IsoWeek
    document: JsonObject
    proposal_diff: JsonObject
    objective_breakdown: JsonObject
    verdict: JsonObject
    weight_set_version: int
    input_version: int
    operation_id: OperationId
    candidate_adjustment: JsonObject | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WeekAdjustmentRecord:
    """One approved concession for one week, kind, and target."""

    id: UUID
    tenant_id: TenantId
    iso_week: IsoWeek
    kind: AdjustmentKind
    target_id: UUID
    reductions: JsonObject
    delta_minutes: int | None
    created_at: datetime
    created_by_operation_id: OperationId


@dataclass(frozen=True, slots=True)
class PinRecord:
    """Where the user put one block this week, and what the solver had chosen instead.

    The record carries a rebuilt ``BindingRef`` and two ``Interval`` values where the table carries
    a JSONB object and four columns, for the reason :class:`BlockOutcomeRecord` does: every reader
    wants the identity as one value and each span as one.

    Neither half of the counterfactual is optional once the pin is complete, which is ``PN3`` and
    ``B1``: a pin states the placement it replaced and what replacing it cost, so the reason panel
    renders both from the pin rather than by walking the edit log. ``objective_delta`` is nullable
    here for one statement's width: the row is held by one statement and priced by a second inside
    one transaction, so a read between the two sees no cost yet.
    """

    id: PinId
    tenant_id: TenantId
    iso_week: IsoWeek
    block_id: BlockId
    binding: BindingRef
    interval: Interval
    superseded_placement: Interval
    objective_delta: float | None
    weight_set_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    """One overlap the user has to answer for, or has answered for, as persistence knows it.

    The record carries a rebuilt ``BindingRef`` and an ``Interval`` where the table carries a JSONB
    object and two columns, for the reason :class:`BlockOutcomeRecord` does: every reader wants the
    identity as one value and the span as one, and rebuilding either in a second place is how two
    readers would come to disagree about which block a row names.

    ``block_id`` is what the week view pairs a conflict with a rendered block on, and it is stored
    rather than derived here because a row already holds it: this record describes a row.

    ``series_uid`` and ``commitment_title`` are the commitment as it stood when the overlap was
    raised, denormalized because the anchor row does not survive the projection horizon rolling past
    it. ``series_uid`` is what a repetition GROUPS on and ``None`` means the commitment has no
    series, so it cannot repeat; ``commitment_title`` is what the raise names, and ``None`` states a
    count without a name.
    """

    id: ConflictId
    tenant_id: TenantId
    iso_week: IsoWeek
    anchor_id: AnchorId
    block_id: BlockId
    binding: BindingRef
    series_uid: str | None
    commitment_title: str | None
    overlap: Interval
    detected_at: datetime
    resolved_at: datetime | None
    resolution: ConflictResolution | None

    @property
    def is_resolved(self) -> bool:
        """Whether this conflict has been answered for. A resolved one is retained, not gone."""
        return self.resolved_at is not None


@dataclass(frozen=True, slots=True)
class BlockOutcomeRecord:
    """What the log says happened to one block, as persistence knows it.

    The record carries a rebuilt ``BindingRef`` and an ``Interval`` where the table carries a
    JSONB object and two columns. That is the whole reason it exists rather than the row being
    passed around: every reader of an outcome wants the identity as one value and the span as one
    value, and rebuilding either in a second place is how two readers would come to disagree about
    which block a row names.

    ``confirmed_at`` is the instant the DAY was settled, not the instant this row was written. A
    row with none is a statement about the block on a day the user has not answered for, which is
    what excludes it from reviews and from learning.
    """

    id: BlockOutcomeId
    tenant_id: TenantId
    block_id: BlockId
    binding: BindingRef
    revision_id: PlanRevisionId
    state: OutcomeState
    actual_minutes: int | None
    actual_interval: Interval | None
    occurred_at: datetime
    confirmed_at: datetime | None

    @property
    def is_confirmed(self) -> bool:
        """Whether the day this outcome belongs to has been settled."""
        return self.confirmed_at is not None

    def as_domain(self) -> RecordedOutcome:
        """The domain value the attribution table is stated over.

        Where persistence meets the invariants: a ``partial`` stored with no minutes, by hand in
        ``psql`` say, is refused here rather than silently attributing its planned span. The check
        constraints refuse the same pair, so this is the second reading of one rule rather than the
        only one.

        No production path calls this yet. It is the seam the live placement reader will project
        through, because the netting is stated over ``RecordedOutcome`` and a repository hands back
        a record; until then the claim above is exercised by the suite rather than by a request.
        """
        return RecordedOutcome(
            binding=self.binding,
            state=self.state,
            actual_minutes=self.actual_minutes,
            actual_interval=self.actual_interval,
        )


@dataclass(frozen=True, slots=True)
class VerdictEventRecord:
    """One recorded verdict transition, exactly as it was stored.

    ``feasible`` is the reading the user was shown rather than :attr:`Verdict.feasible`, which is
    always ``False`` on a probe verdict: capacity arithmetic may not claim a week works, so what a
    probe that found nothing reports is that it found no gap. The projection that writes this states
    that translation once; a reader of this record reads "the week was reported able to hold its
    commitments".

    ``shortfall_kinds`` carries no duplicates and holds the kinds in the order the verdict named
    them, so two rows recording one verdict are equal by value.
    """

    id: VerdictEventId
    tenant_id: TenantId
    iso_week: IsoWeek
    occurred_at: datetime
    provenance: Provenance
    feasible: bool
    shortfall_minutes: int
    shortfall_kinds: tuple[ShortfallKind, ...]
    surface: VerdictSurface
    session_mode_active: bool
    input_version: int
    caused_by_operation_id: OperationId | None
