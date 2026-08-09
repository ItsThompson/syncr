"""The outcome log as the rotation cursor and outstanding debt read it.

A second reader over ``block_outcomes``, beside the one that records and confirms, because the two
answer different questions and neither is the other's projection. :mod:`syncr_api.plans.reality`
answers "what happened to this block", keyed by block, for a ledger and a write. This answers "what
happened to this habit's occurrences", keyed by the entity a binding names, for two derivations that
count rows.

**It lives here rather than in the habit package** for the reason the concession routes read plan
storage's adjustment repository: the package that owns a table owns the statements over it. The
habit service acquires this through the protocol it declares, so nothing in that package names a
column of this one.

**The projection is total and it drops nothing.** A missing row is a cursor one variant behind and a
duplicated row is one variant ahead, so the read is an equality over the habits asked for rather
than a filter that could silently narrow. The at-most-one-row-per-occurrence precondition the
protocol states is held by the write path's identity, ``(tenant_id, block_id)``, so this reader has
no rule to apply for it: a habit occurrence in one week is one block, and one block is one row.

**Neither predicate is the correctness boundary, and saying so matters.** Both derivations filter
the rows they are handed by ``habit_id`` themselves, so a read that returned every row of the log
would still produce the right cursor and the right debt figure. What the two predicates buy is the
READ: they bound it to the rows a caller asked about, and they are what lets the expression index
serve it. The index is ``(tenant_id, kind, entity_id)``, so stating the kind bounds the scan to the
one range that pair holds. Omitting it does not lose the index: the scan then covers every entry
the tenant holds and rechecks each against the entity. That is why the statement is asserted rather
than only its answer: what a missing predicate costs has no symptom other than a slower request.

**The key spellings are the writer's own.** The two extractions name the constants
``stored_binding`` writes rather than strings spelled a second time, which is what makes a silent
zero impossible: a guessed key would match no row and every rotation habit would read as sitting on
its first variant with nothing reporting it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.repository import TenantScopedReader
from syncr_api.plans.config import BLOCK_OUTCOMES_TABLE
from syncr_api.plans.facts import BlockOutcome
from syncr_api.plans.stored_documents import ENTITY_ID, KIND, OCCURRENCE_KEY
from syncr_api.plans.stored_values import read_id, read_text
from syncr_domain.identity import BindingKind
from syncr_domain.outcomes import HabitOutcome, OutcomeState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select

    from syncr_domain.identifiers import HabitId


class HabitOutcomeLog(TenantScopedReader):
    """Every outcome of one tenant's whose binding names a habit, projected for the derivations."""

    async def read(self, habit_ids: Sequence[HabitId]) -> tuple[HabitOutcome, ...]:
        """The outcomes of these habits' occurrences. Writes nothing.

        One statement for the whole collection, so rendering a list of habits is one read. The order
        is not part of the contract, because both derivations are counts; the rows come back in the
        index's own order.

        An empty request answers without a read. An empty ``IN`` already matches nothing, so this
        saves the round trip rather than changing the answer: a tenant with no habits is a real case
        and the habit collection route reaches it on every render.
        """
        if not habit_ids:
            return ()
        rows = await self._session.scalars(self.statement(habit_ids))
        return tuple(_as_habit_outcome(row) for row in rows)

    def statement(self, habit_ids: Sequence[HabitId]) -> Select[tuple[BlockOutcome]]:
        """The read this projection is taken over. Public so the SQL itself can be asserted.

        Separated from :meth:`read` for the reason the scoped-statement rules are: what this class
        owes its callers is a query the expression index can serve, and that is a property of the
        statement rather than of the rows it happens to return today.
        """
        return self.scoped_select(BlockOutcome).where(
            BlockOutcome.binding[KIND].astext == BindingKind.HABIT.value,
            BlockOutcome.binding[ENTITY_ID].astext.in_([str(one) for one in habit_ids]),
        )


def _as_habit_outcome(row: BlockOutcome) -> HabitOutcome:
    """One stored row as the projection the two derivations take.

    The binding's own components are read rather than the row's other columns, because the binding
    is what survives the habit ceasing to exist and it is what the re-derivation keys on. Each is
    parsed through the reader a stored document uses, so a row written past the write path names the
    same identity a block does or is refused where it is read.

    The occurrence key is then checked against the one derivation of a habit key inside
    ``HabitOutcome``, so a row spelling an index some other way is refused here rather than matching
    no block two layers down.
    """
    field = f"{BLOCK_OUTCOMES_TABLE}.binding"
    return HabitOutcome(
        habit_id=read_id(row.binding.get(ENTITY_ID), field=f"{field}.{ENTITY_ID}"),
        occurrence_key=read_text(
            row.binding.get(OCCURRENCE_KEY), field=f"{field}.{OCCURRENCE_KEY}"
        ),
        state=OutcomeState(row.state),
        occurred_at=row.occurred_at,
        confirmed_at=row.confirmed_at,
    )
