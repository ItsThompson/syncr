"""``PlanConflictRepository``: raise a conflict once, list them, and record an answer.

A conflict is a permanent record, so this repository has no delete path. What it does have is a
narrow update: the resolution and the instant it was chosen, written together, once. Everything
else about a row is a fact from the moment it was raised.

## Raising is idempotent, and the database is what makes it so

Detection runs at ingest on every sync that moved a commitment, and again on the commit path of
every solve, so the same overlap arrives many times. The partial unique index on
``(tenant_id, anchor_id, block_id)`` covers exactly the rows that already carry a question or an
accepted answer, and the insert names that index as its conflict target, so a second raise of an
overlap the user is already looking at inserts nothing and reports nothing raised. That also
settles the race between two workers detecting the same overlap in one instant: the second insert
does nothing rather than raising a duplicate, and neither caller has to read before writing.

A conflict answered with ``moved`` or ``retyped`` is outside that index deliberately. Both answers
asked for a change, so the same collision appearing afterwards is a new event the user has to see
rather than the same question asked twice.

## What a raise answers with is what was newly raised

The notification is the only one this product sends, so the caller has to know which conflicts are
news. The insert returns the rows it actually wrote, which is that set exactly: a caller that
counted the detections instead would notify about a collision the user has already answered for.

## The commitment is recorded, because the anchor row does not survive

A raise stores the commitment's series key and its name beside the overlap. Both are facts about the
anchor and neither can be read back later: reconciliation deletes an occurrence its feed stopped
publishing, and the projection horizon rolling forward does exactly that to every past occurrence of
a recurring commitment. So the row a month-old conflict names has usually gone, while the weekly
session's repeated-collision item is stated over the same commitment in three or more weeks.

The caller supplies both, because only the caller holds them. Detection works from two plan
documents or from an assembly's resolved shapes, and neither carries a series key: an anchor
block's binding names the OCCURRENCE. So :meth:`PlanConflictRepository.raise_all` takes a mapping
from anchor to :class:`Commitment`, and an anchor absent from it stores nulls, which is the honest
record for one that had already gone when the raise happened. The argument is required, so absence
is a fact rather than something a caller forgot.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.config import UNANSWERED_CONFLICT
from syncr_api.plans.facts import UNANSWERED_CONFLICT_COLUMNS, PlanConflict
from syncr_api.plans.records import ConflictRecord
from syncr_api.plans.stored_documents import read_binding, stored_binding
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_api.plans.config import ConflictResolution
    from syncr_api.plans.overlaps import DetectedConflict
    from syncr_domain.identifiers import AnchorId, ConflictId


@dataclass(frozen=True, slots=True, kw_only=True)
class Commitment:
    """An imported commitment as a retained conflict records it: its series, and its name.

    ``series_uid`` is ``None`` for a one-off, which is a first-class answer rather than a gap: a
    commitment with no series cannot recur, so it can never be part of a repetition.
    """

    series_uid: str | None
    title: str


class CommitmentReader(Protocol):
    """What a raise on the solve commit path asks for the commitments it is about to record.

    Declared here, beside the write that needs it, and implemented by the package that owns the
    ``anchors`` table. A conflict raised at ingest needs no reader: that pass already holds the rows
    it reconciled, and reading them a second time would be a second answer to what the feed said.
    """

    async def commitments(self, anchor_ids: Sequence[AnchorId]) -> Mapping[AnchorId, Commitment]:
        """The commitment each of these anchors is, omitting any whose row no longer exists."""
        ...


# How many conflicts one list read returns. A week raises a handful and the open set across every
# week is smaller still, because each one blocks a banner until it is answered. The bound is what
# stops a deployment that stopped resolving them from turning a read into an unbounded one.
LIST_LIMIT = 200

# The two orders a bounded read of this table takes, and the id settles a tie either way: two
# commitments can meet two blocks at one instant, and a page has to be reproducible.
_AS_THEY_OCCUR = (PlanConflict.overlap_starts_at, PlanConflict.id)
_NEWEST_FIRST = (PlanConflict.overlap_starts_at.desc(), PlanConflict.id.desc())


class PlanConflictRepository(TenantScopedRepository):
    """One tenant's conflicts: raised once, listed, and answered for."""

    async def raise_all(
        self,
        detected: Sequence[DetectedConflict],
        *,
        at: datetime,
        commitments: Mapping[AnchorId, Commitment],
    ) -> tuple[ConflictRecord, ...]:
        """Raise each of these overlaps that is not already asked about, newly raised first.

        Answers with the rows this call wrote and nothing else, so the caller notifies about what
        is news rather than about every overlap that still exists.

        ``commitments`` is what each row records about the anchor it names. An anchor absent from it
        stores nulls, which says the commitment's row had already gone: see the module note.
        """
        if not detected:
            return ()
        statement = (
            insert(PlanConflict)
            .values(
                [
                    self._row(conflict, at=at, commitment=commitments.get(conflict.anchor_id))
                    for conflict in detected
                ]
            )
            .on_conflict_do_nothing(
                index_elements=list(UNANSWERED_CONFLICT_COLUMNS),
                index_where=UNANSWERED_CONFLICT,
            )
            .returning(PlanConflict)
        )
        raised = await self._session.scalars(statement)
        return tuple(_as_record(row) for row in raised)

    async def find(self, conflict_id: ConflictId) -> ConflictRecord | None:
        """The conflict with this id, or ``None`` when this tenant has no such row."""
        found = await self._session.scalar(
            self.scoped_select(PlanConflict).where(PlanConflict.id == conflict_id)
        )
        return _as_record(found) if found is not None else None

    async def list_all(
        self, *, resolved: bool | None = None, limit: int = LIST_LIMIT
    ) -> tuple[ConflictRecord, ...]:
        """This tenant's conflicts, optionally narrowed by state, bounded either way.

        ``resolved`` is a tri-state on purpose: the open set is what the banner reads, the resolved
        set is what a repeated collision is computed over, and both together are what a week view
        renders. Answering only the open ones would make the retained rows unreachable.

        **The order follows which of those reads it is.** The open set is read in the order the
        overlaps occur, because that is the order a banner lists what is coming, and the set is
        small: each member holds a banner until it is answered. Any read that can include resolved
        rows is a page of a history that is never pruned, so it is read newest first, for the reason
        a revision history is: a page of the oldest 200 rows of a permanent table can never reach
        the recent end, and the recent end is where a repetition is.
        """
        statement = self.scoped_select(PlanConflict)
        if resolved is not None:
            statement = statement.where(PlanConflict.resolved_at.is_not(None) == resolved)
        order = _AS_THEY_OCCUR if resolved is False else _NEWEST_FIRST
        rows = await self._session.scalars(statement.order_by(*order).limit(limit))
        return tuple(_as_record(row) for row in rows)

    async def for_week(
        self, iso_week: IsoWeek, *, limit: int = LIST_LIMIT
    ) -> tuple[ConflictRecord, ...]:
        """Every conflict raised in one week, earliest overlap first, resolved ones included."""
        rows = await self._session.scalars(
            self.scoped_select(PlanConflict)
            .where(PlanConflict.iso_week == str(iso_week))
            .order_by(PlanConflict.overlap_starts_at, PlanConflict.id)
            .limit(limit)
        )
        return tuple(_as_record(row) for row in rows)

    async def for_weeks(
        self, weeks: Sequence[IsoWeek], *, limit: int = LIST_LIMIT
    ) -> tuple[ConflictRecord, ...]:
        """Every conflict raised in any of ``weeks``, newest week first, resolved ones included.

        One statement for the whole window, because the reader is the weekly session's
        repeated-collision item and that is one pass over the rows: a read per week would be a read
        per week to answer one question about all of them.

        **The window is the point rather than the statement count.** :meth:`list_all` reads the
        newest page of a table that is never pruned, across every week the tenant has ever had, so
        a pattern the user fixed eight months ago would be raised in every session from now on. A
        raise about a pattern has to be bounded to a period the way the chronic-skip run and the
        repeated-pin run already are.

        Newest week first, so the bound cuts the oldest weeks rather than the recent end: a pattern
        is about weeks the user has just lived.
        """
        if not weeks:
            return ()
        rows = await self._session.scalars(
            self.scoped_select(PlanConflict)
            .where(PlanConflict.iso_week.in_([str(one) for one in weeks]))
            .order_by(PlanConflict.iso_week.desc(), PlanConflict.overlap_starts_at, PlanConflict.id)
            .limit(limit)
        )
        return tuple(_as_record(row) for row in rows)

    async def resolve(
        self, conflict_id: ConflictId, *, resolution: ConflictResolution, at: datetime
    ) -> ConflictRecord | None:
        """Record how this conflict was answered, and answer ``None`` if it already was.

        The statement is what decides legality: it matches only an unresolved row, so two answers
        arriving together produce one resolution rather than the second overwriting the first. A
        caller that reads ``None`` either holds another tenant's identifier or lost that race, and
        it can tell those apart by reading the row.
        """
        resolved = await self._session.scalar(
            self.scoped_update(PlanConflict)
            .where(PlanConflict.id == conflict_id, PlanConflict.resolved_at.is_(None))
            .values(resolution=resolution, resolved_at=at)
            .returning(PlanConflict)
        )
        return _as_record(resolved) if resolved is not None else None

    def _row(
        self, conflict: DetectedConflict, *, at: datetime, commitment: Commitment | None
    ) -> dict[str, object]:
        """One detection as the row it becomes, with every derived column derived here.

        The block id and the week both come from the detection's own binding rather than from a
        caller, for the reason a revision's week does: a column describing something the value
        does not name can only disagree with it.
        """
        return {
            "id": uuid4(),
            TENANT_ID_COLUMN: self.tenant_id,
            "iso_week": str(conflict.iso_week),
            "anchor_id": conflict.anchor_id,
            "block_id": conflict.block_id,
            "binding": stored_binding(conflict.binding),
            "series_uid": None if commitment is None else commitment.series_uid,
            "commitment_title": None if commitment is None else commitment.title,
            "overlap_starts_at": conflict.overlap.start,
            "overlap_ends_at": conflict.overlap.end,
            "detected_at": at,
        }


def _as_record(conflict: PlanConflict) -> ConflictRecord:
    return ConflictRecord(
        id=conflict.id,
        tenant_id=conflict.tenant_id,
        iso_week=IsoWeek.parse(conflict.iso_week),
        anchor_id=conflict.anchor_id,
        block_id=conflict.block_id,
        binding=read_binding(deepcopy(conflict.binding), field="binding"),
        series_uid=conflict.series_uid,
        commitment_title=conflict.commitment_title,
        overlap=Interval(conflict.overlap_starts_at, conflict.overlap_ends_at),
        detected_at=conflict.detected_at,
        resolved_at=conflict.resolved_at,
        # The column's value set is enforced by a check constraint, so the narrowing states what
        # the database already guarantees rather than re-checking it.
        resolution=cast("ConflictResolution | None", conflict.resolution),
    )
