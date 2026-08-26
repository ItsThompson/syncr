"""The outcome log as the rotation cursor reads it, and as the stored charge restates from.

A second reader over ``block_outcomes``, beside the one that records and confirms, because the two
answer different questions and neither is the other's projection. :mod:`syncr_api.plans.reality`
answers "what happened to this block", keyed by block, for a ledger and a write. This answers "what
happened to this habit's occurrences", keyed by the entity a binding names.

**It lives here rather than in the habit package** for the reason the concession routes read plan
storage's adjustment repository: the package that owns a table owns the statements over it. The
habit service acquires this through the protocol it declares, so nothing in that package names a
column of this one.

**The read is total for the cursor, and that totality is the bound stated honestly.** A missing row
is a cursor one variant behind and a duplicated row is one variant ahead, so the read is an equality
over the habits asked for rather than a filter that could silently narrow. The at-most-one-row-per-
occurrence precondition behind that equality is held by the write path's identity,
``(tenant_id, block_id)``, so this reader has no rule to apply for it: a habit occurrence in one
week is one block, and one block is one row. No window can narrow the read either: a count modulo
the variant list cannot survive one, because dropping any confirmed completion moves every later
week onto the wrong variant. That is why this projection stays unbounded over the tenant's history
while every other reader of the log takes a window -- the rows it walks are the rows the cursor is.

**Debt no longer derives here, and saying so matters.** The walked charge of confirmed misses less
completed make-ups is stored on the habit row (``charged_misses``) and restated by the outcome
write through :mod:`syncr_api.habits.charged`, from this same log, inside the transaction that
changed it. A reader that cannot afford this read's whole history therefore still answers with the
figure the log supports, and the figure cannot fall when part of a habit's history ages out of any
window a request takes, because no figure a user acts on depends on such a window. What still reads
rows bounded in time here is :meth:`HabitOutcomeLog.settled_within`, the weekly session's slice for
an ``escalate`` habit, and :meth:`HabitOutcomeLog.latest`, the interval cadence's due rule.

**``latest`` is the bounded half of the seam.** The week assembler's interval rule asks when each
habit last recorded an occurrence, and the answer only needs rows as far back as one declared
interval past the week being assembled. That bound keeps the read inside the range the expression
index serves rather than walking every row of the tenant's history for instants the rule never
reads, and it is why the method takes ``since`` rather than answering from an unbounded read.

**Neither predicate is the correctness boundary, and saying so matters.** Both extractions filter
the rows they are handed by ``habit_id`` themselves, so a read that returned every row of the log
would still produce the right cursor. What the two predicates buy is the READ: they bound it to the
rows a caller asked about, and they are what lets the expression index serve it. The index is
``(tenant_id, kind, entity_id)``, so stating the kind bounds the scan to the one range that pair
holds. Omitting it does not lose the index: the scan then covers every entry the tenant holds and
rechecks each against the entity. That is why the statement is asserted rather than only its answer:
what a missing predicate costs has no symptom other than a slower request.

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
from syncr_api.plans.stored_documents import ENTITY_ID, KIND, MAKE_UP, OCCURRENCE_KEY
from syncr_api.plans.stored_values import read_id, read_optional_flag, read_text
from syncr_domain.identity import BindingKind
from syncr_domain.outcomes import HabitOutcome, OutcomeState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy import Select

    from syncr_domain.identifiers import HabitId
    from syncr_domain.intervals import Instant, Interval


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

    async def latest(
        self, habit_ids: Sequence[HabitId], *, since: Instant
    ) -> Mapping[HabitId, Instant | None]:
        """When each habit last recorded an occurrence, among the rows on or after ``since``.

        One entry per requested id, with ``None`` where the window holds no row, so a caller reads
        "never recorded" out of the mapping instead of an absent key. The reduction happens here
        rather than in the caller because the rows come back in whatever order the index holds them
        and a latest-of is order-dependent: two readers of one unordered read could otherwise pick
        different rows.
        """
        if not habit_ids:
            return {}
        rows = await self._session.scalars(self.recent_statement(habit_ids, since=since))
        latest_seen: dict[HabitId, Instant | None] = dict.fromkeys(habit_ids)
        for row in rows:
            outcome = _as_habit_outcome(row)
            seen = latest_seen[outcome.habit_id]
            if seen is None or outcome.occurred_at > seen:
                latest_seen[outcome.habit_id] = outcome.occurred_at
        return latest_seen

    def recent_statement(
        self, habit_ids: Sequence[HabitId], *, since: Instant
    ) -> Select[tuple[BlockOutcome]]:
        """The bounded read :meth:`latest` is taken over. Public so the SQL itself can be asserted.

        The window predicate sits beside the projection's own two, so the statement still leads
        with everything the expression index reads and the bound narrows the range within it.
        """
        return self.statement(habit_ids).where(BlockOutcome.occurred_at >= since)

    async def settled_within(
        self, habit_ids: Sequence[HabitId], *, span: Interval
    ) -> tuple[HabitOutcome, ...]:
        """The outcomes of these habits whose day was confirmed inside ``span``. Writes nothing.

        Half-open like every span in this product: confirmed at ``span.start`` is inside, confirmed
        at ``span.end`` belongs to whatever holds that instant. An unconfirmed row names no settled
        day at all and reaches no raise under any policy, so leaving it out costs no figure.
        """
        if not habit_ids:
            return ()
        rows = await self._session.scalars(self.settled_statement(habit_ids, span=span))
        return tuple(_as_habit_outcome(row) for row in rows)

    def settled_statement(
        self, habit_ids: Sequence[HabitId], *, span: Interval
    ) -> Select[tuple[BlockOutcome]]:
        """The bounded read :meth:`settled_within` is taken over. Public so the SQL can be asserted.

        Both bounds sit beside the projection's own two predicates, so the statement still leads
        with everything the expression index reads and the window narrows within it.
        """
        return self.statement(habit_ids).where(
            BlockOutcome.confirmed_at >= span.start,
            BlockOutcome.confirmed_at < span.end,
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

    The make-up mark reads as its default when the row states none, because a row written before
    the mark existed was written about an expansion this code cannot see: reading it as a fresh
    occurrence is the honest answer, and reading it as a discharge would forgive a miss nothing
    earned.
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
        is_make_up=read_optional_flag(row.binding.get(MAKE_UP), field=f"{field}.{MAKE_UP}"),
    )
