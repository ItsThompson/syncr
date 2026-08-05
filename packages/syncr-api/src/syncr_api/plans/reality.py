"""``BlockOutcomeRepository``: the outcome log, and the two writes that change it.

The log answers one question per block, "what happened to this", and it is the substrate the
rotation cursor, outstanding debt, the retro, the duration fitter, and the probe's demand all
rest on. One decision governs the shape of a row, and it is worth stating in full.

**One outcome row per block, ever.** A block id is a digest of the week and the binding, so one
content instance in one week keeps one id however many revisions place it, and this table's
identity is ``(tenant_id, block_id)``. The alternative reading, a row per plan of record, is what
the schema first shipped. It was narrowed because every consumer of the log is a COUNT over the
rows it is handed, and a count cannot tell a duplicate from a second occurrence:

- ``syncr_domain.cursor`` advances a rotation once per confirmed completion, so two rows under one
  occurrence key move the gym split past the muscle group the user actually trained.
- ``syncr_domain.debt`` charges one miss per row, so one skip delivered twice is owed twice until
  the cap clamps it.

``HabitOutcomeReader``'s precondition names exactly that hazard and leaves the resolution to the
reader. Resolving it in a reader would mean choosing the latest revision or the newest
confirmation, and neither is a rule with any product meaning: the user recorded one thing about
one block, and a revision boundary is not something they can see. So the write path holds the
invariant and the unique index makes it structural rather than a rule each reader remembers.

``revision_id`` therefore names the plan of record the outcome was recorded AGAINST, restated when
a correction is recorded. Nothing is lost by that restatement: every revision document is itself
permanent and immutable, so the plan the user was looking at stays readable.

**Two writes, and neither is a general update.** :meth:`record` states what the user said happened
to one block and never touches ``confirmed_at``, because recording an exception during the day is
not settling the day, and that is what keeps an unconfirmed row out of reviews and learning.
:meth:`settle` is the day's confirmation: it presumes every block with no row yet and stamps the
day's rows, keeping the FIRST confirmation instant so confirming twice changes nothing.

**A row is never deleted.** An outcome is a fact about a week that happened, and it is retained
even after its binding's entity is gone, which is why the binding is denormalized onto it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.config import BLOCK_OUTCOMES_TABLE
from syncr_api.plans.facts import BlockOutcome
from syncr_api.plans.records import BlockOutcomeRecord
from syncr_api.plans.stored_documents import read_binding, stored_binding
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syncr_domain.identifiers import PlanRevisionId
    from syncr_domain.identity import BindingRef, BlockId
    from syncr_domain.outcomes import RecordedOutcome

# The columns ``(tenant_id, block_id)`` unique index covers, as the upsert names them.
_IDENTITY = (TENANT_ID_COLUMN, "block_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class Presumption:
    """One block a day's confirmation has to record something about.

    A block with no row of its own is ``presumed`` complete with no user action, so confirming the
    day is what turns that reading into a row. The four fields are what a row needs beyond its
    state: which block, what it held, which plan of record placed it, and when it was scheduled.
    """

    block_id: BlockId
    binding: BindingRef
    revision_id: PlanRevisionId
    occurred_at: datetime


class BlockOutcomeRepository(TenantScopedRepository):
    """One tenant's outcome log: one row per block, recorded and corrected in place."""

    async def record(
        self,
        outcome: RecordedOutcome,
        *,
        block_id: BlockId,
        revision_id: PlanRevisionId,
        occurred_at: datetime,
    ) -> None:
        """State what happened to one block, replacing whatever the log said before.

        The outcome arrives as the domain value rather than as a state and two loose columns, so
        the pair each state carries is checked before a statement is built: a ``partial`` with no
        minutes and a ``moved`` with no interval are both refused where the value is constructed,
        and the check constraints are the second line rather than the only one.
        """
        await self._session.execute(
            insert(BlockOutcome)
            .values([self._row(outcome, block_id, revision_id, occurred_at)])
            .on_conflict_do_update(
                index_elements=list(_IDENTITY),
                set_={
                    "binding": stored_binding(outcome.binding),
                    "revision_id": revision_id,
                    "state": outcome.state.value,
                    "actual_minutes": outcome.actual_minutes,
                    "actual_starts_at": _start_of(outcome.actual_interval),
                    "actual_ends_at": _end_of(outcome.actual_interval),
                    "occurred_at": occurred_at,
                },
            )
        )

    async def settle(self, presumptions: Sequence[Presumption], *, at: datetime) -> int:
        """Record the day these blocks belong to, and answer how many rows it settled.

        Two statements, in one transaction, and the order is what makes the answer complete: the
        presumptions land first so a block the user never touched has a row to stamp, and the
        stamp then covers every row of the day including the exceptions they did record.

        ``confirmed_at`` is set only where it is null, so a day confirmed twice keeps the instant
        it was first settled at. That instant is what says WHEN the user answered for the day, and
        moving it on every later correction would make a day confirmed on Monday and corrected in
        March read as settled in March.
        """
        if not presumptions:
            return 0
        await self._session.execute(
            insert(BlockOutcome)
            .values([self._presumed(one) for one in presumptions])
            .on_conflict_do_nothing(index_elements=list(_IDENTITY))
        )
        return await self._affected_rows(
            self.scoped_update(BlockOutcome)
            .where(
                BlockOutcome.block_id.in_([one.block_id for one in presumptions]),
                BlockOutcome.confirmed_at.is_(None),
            )
            .values(confirmed_at=at)
        )

    async def for_span(self, span: Interval) -> tuple[BlockOutcomeRecord, ...]:
        """Every outcome whose block was scheduled inside ``span``, earliest first.

        ``occurred_at`` is the block's own start, so this is the read that answers "the outcomes of
        this day" and "the outcomes of these four weeks" from one index and one rule about which
        day a block belongs to.
        """
        rows = await self._session.scalars(
            self.scoped_select(BlockOutcome)
            .where(BlockOutcome.occurred_at >= span.start, BlockOutcome.occurred_at < span.end)
            .order_by(BlockOutcome.occurred_at, BlockOutcome.block_id)
        )
        return tuple(_as_record(row) for row in rows)

    def _row(
        self,
        outcome: RecordedOutcome,
        block_id: BlockId,
        revision_id: PlanRevisionId,
        occurred_at: datetime,
    ) -> dict[str, object]:
        return {
            "id": uuid4(),
            TENANT_ID_COLUMN: self.tenant_id,
            "block_id": block_id,
            "binding": stored_binding(outcome.binding),
            "revision_id": revision_id,
            "state": outcome.state.value,
            "actual_minutes": outcome.actual_minutes,
            "actual_starts_at": _start_of(outcome.actual_interval),
            "actual_ends_at": _end_of(outcome.actual_interval),
            "occurred_at": occurred_at,
        }

    def _presumed(self, presumption: Presumption) -> dict[str, object]:
        return {
            "id": uuid4(),
            TENANT_ID_COLUMN: self.tenant_id,
            "block_id": presumption.block_id,
            "binding": stored_binding(presumption.binding),
            "revision_id": presumption.revision_id,
            "state": OutcomeState.PRESUMED.value,
            "actual_minutes": None,
            "actual_starts_at": None,
            "actual_ends_at": None,
            "occurred_at": presumption.occurred_at,
        }


def _as_record(row: BlockOutcome) -> BlockOutcomeRecord:
    """One stored row as the frozen view, with its two composite values rebuilt.

    The binding and the interval are parsed through the readers a stored document uses, so a row
    written past this repository names the same identity a block does or is refused where it is
    read. The state is narrowed rather than re-checked: a check constraint already holds the
    column to the vocabulary.
    """
    return BlockOutcomeRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        block_id=row.block_id,
        binding=read_binding(row.binding, field=f"{BLOCK_OUTCOMES_TABLE}.binding"),
        revision_id=row.revision_id,
        state=OutcomeState(row.state),
        actual_minutes=row.actual_minutes,
        actual_interval=_interval_of(row.actual_starts_at, row.actual_ends_at),
        occurred_at=row.occurred_at,
        confirmed_at=row.confirmed_at,
    )


def _interval_of(starts_at: datetime | None, ends_at: datetime | None) -> Interval | None:
    """The span two nullable columns name, or nothing when the row states none.

    A check constraint holds the pair to both or neither, so one half without the other is a row
    the database refuses rather than a case to resolve here.
    """
    if starts_at is None or ends_at is None:
        return None
    return Interval(starts_at, ends_at)


def _start_of(interval: Interval | None) -> datetime | None:
    return None if interval is None else interval.start


def _end_of(interval: Interval | None) -> datetime | None:
    return None if interval is None else interval.end
