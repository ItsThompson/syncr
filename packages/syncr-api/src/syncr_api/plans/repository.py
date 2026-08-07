"""``PlanRepository``: append a revision, read revisions, and nothing else.

The class extends :class:`~syncr_api.core.repository.TenantScopedReader` rather than
``TenantScopedRepository``, so it inherits no statement builder that could change a stored
row. That is what makes append-only structural: there is no update path to leave unused
and no delete path to remember not to call. A boundary test reads this class's whole
public surface, inherited members included, and fails on anything that could modify a row.

Three reasons force it, and all three lose data that cannot be recovered afterwards. The
user can confirm any past day at any time, so a past week's plan of record has to still
exist. The solver's churn term is measured against the plan the user last approved. The
learning layer trains on the pair of what was proposed and what was kept.

``iso_week`` is never accepted as an argument here. It is derived from the document, in
``derivation.py``, so the column cannot describe a week the document does not.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from syncr_api.core.repository import TenantScopedReader
from syncr_api.plans.config import APPROVED, RevisionReason, RevisionStatus
from syncr_api.plans.derivation import derive_iso_week
from syncr_api.plans.errors import RevisionRejected
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.records import PlanRevisionRecord
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Select

    from syncr_api.core.columns import JsonDocument
    from syncr_domain.identifiers import PlanRevisionId
    from syncr_domain.intervals import Interval

# How many revisions a week's history read returns by default. A week appends 3 to 6, so
# this covers a whole week's history without a caller stating a number.
DEFAULT_HISTORY_LIMIT = 50


class PlanRepository(TenantScopedReader):
    """The plan of record for one tenant: appended once, read forever."""

    async def append(
        self,
        *,
        document: JsonDocument,
        objective_breakdown: JsonDocument,
        status: RevisionStatus,
        reason: RevisionReason,
        weight_set_version: int,
        input_version: int,
        created_at: datetime,
        approved_at: datetime | None = None,
        supersedes_id: PlanRevisionId | None = None,
    ) -> PlanRevisionRecord:
        """Append one revision, deriving every document-describing column from the document.

        Raises :class:`~syncr_api.plans.errors.RevisionRejected` when an approved revision
        states no instant of assent. The database rejects that pair too; the guard is here as
        well so the failure names the invariant instead of naming a constraint, and so it
        surfaces at the call that broke it rather than at the transaction's commit.
        """
        if status == APPROVED and approved_at is None:
            raise RevisionRejected(
                "an approved revision must state when it was approved: the retro reads "
                "the plan of record as of a date, and the churn baseline reads its instant"
            )
        iso_week = derive_iso_week(document)
        revision = PlanRevision(
            id=uuid4(),
            tenant_id=self.tenant_id,
            iso_week=str(iso_week),
            status=status,
            reason=reason,
            document=dict(document),
            objective_breakdown=dict(objective_breakdown),
            weight_set_version=weight_set_version,
            input_version=input_version,
            supersedes_id=supersedes_id,
            created_at=created_at,
            approved_at=approved_at,
        )
        self._session.add(revision)
        # Flushed here so a rejected row surfaces as this call's failure rather than at
        # commit, after the caller has reported success to whoever asked.
        await self._session.flush()
        return _as_record(revision)

    async def find(self, revision_id: PlanRevisionId) -> PlanRevisionRecord | None:
        """The revision with this id, or ``None`` when this tenant has no such row."""
        found = await self._session.scalar(
            self.scoped_select(PlanRevision).where(PlanRevision.id == revision_id)
        )
        return _as_record(found) if found is not None else None

    async def latest(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        """The live plan for this week: the newest revision, whatever its status."""
        return await self._newest(iso_week, status=None)

    async def latest_approved(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        """The churn baseline: the newest revision the user assented to."""
        return await self._newest(iso_week, status=APPROVED)

    async def history(
        self, iso_week: IsoWeek, *, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> list[PlanRevisionRecord]:
        """This week's revisions, newest first."""
        rows = await self._session.scalars(self._week(iso_week).limit(limit))
        return [_as_record(row) for row in rows]

    async def approved_in(self, span: Interval) -> tuple[PlanRevisionRecord, ...]:
        """Every revision the user assented to inside ``span``, oldest first.

        Across weeks rather than within one, because this is what the proposal-acceptance metric's
        numerator is counted over: a period, not a week. Ordered by the instant of ASSENT rather
        than of creation, because assent is the act being counted and a proposal may be approved
        days after the solve that produced it.
        """
        rows = await self._session.scalars(
            self.scoped_select(PlanRevision)
            .where(
                PlanRevision.status == APPROVED,
                PlanRevision.approved_at >= span.start,
                PlanRevision.approved_at < span.end,
            )
            .order_by(PlanRevision.approved_at.asc(), PlanRevision.id.asc())
        )
        return tuple(_as_record(row) for row in rows)

    def _week(self, iso_week: IsoWeek) -> Select[tuple[PlanRevision]]:
        """This week's revisions, newest first. The one statement of that order.

        The id is a tie-break rather than an order anyone reads: two revisions appended
        against one instant would otherwise come back in whichever order the scan
        produced, and "the live plan" has to be one row.
        """
        return (
            self.scoped_select(PlanRevision)
            .where(PlanRevision.iso_week == str(iso_week))
            .order_by(PlanRevision.created_at.desc(), PlanRevision.id.desc())
        )

    async def _newest(
        self, iso_week: IsoWeek, *, status: RevisionStatus | None
    ) -> PlanRevisionRecord | None:
        statement = self._week(iso_week)
        if status is not None:
            statement = statement.where(PlanRevision.status == status)
        found = await self._session.scalar(statement.limit(1))
        return _as_record(found) if found is not None else None


def _as_record(revision: PlanRevision) -> PlanRevisionRecord:
    return PlanRevisionRecord(
        id=revision.id,
        tenant_id=revision.tenant_id,
        iso_week=IsoWeek.parse(revision.iso_week),
        # The column's value set is enforced by a check constraint, so the narrowing here
        # states what the database already guarantees rather than re-checking it.
        status=cast("RevisionStatus", revision.status),
        reason=cast("RevisionReason", revision.reason),
        document=deepcopy(revision.document),
        objective_breakdown=deepcopy(revision.objective_breakdown),
        weight_set_version=revision.weight_set_version,
        input_version=revision.input_version,
        supersedes_id=revision.supersedes_id,
        created_at=revision.created_at,
        approved_at=revision.approved_at,
    )
