"""``PinRepository``: the live constraint a pin is, and the three writes that change it.

A pin is two things at once, and this table holds only the first: it is the constraint this week's
solve may not move, and it is a training label. The label is the ``edit_events`` row written in the
same transaction, which is append-only and never pruned. So the rules that look contradictory in
section 07 are one rule once the pair is read together:

| Rule | What holds it |
|---|---|
| the record of a pin persists permanently | the edit event, which nothing here can reach |
| every pin persists the placement it superseded | ``NOT NULL``, and :meth:`price` for the cost |
| the objective delta is stored, never recomputed | no write here recomputes one |
| releasing a pin retains its record as training data | :meth:`release`, whose event survives it |

**One pin per block, so :meth:`hold` upserts.** A person holds one answer at a time to "where does
this content go this week", and a second drag of one block states that answer again. Two rows would
constrain one solve to two intervals, and which one won would be read order: the solver seeds a
pinned binding from the pin naming it. The unique index over ``(tenant_id, block_id)`` is what makes
that structural, and the upsert names that index as its conflict target.

**A block id is what the identity is stated over, and the route is handed one.** The client drags a
rendered block, so a block id is the only handle a request carries; it is also a digest of the week
and the binding, so per-week uniqueness follows from it and the binding travels beside it for the
readers that need an identity they can compare across weeks.

**A pin is written in two statements, and the second states its cost.** :meth:`hold` writes the row
and :meth:`price` writes the delta, both in the caller's transaction, so nothing outside it reads a
pin without one. The delta is a difference of two objective evaluations over one assembly of the
week, and the caller measures it in the assembly it takes BEFORE this row is written: what a pin
cost is a fact about the state the user chose in, and a frame that already counts the pin cannot
express it. So the caller holds the figure before it holds the row.

**Nothing here reads a clock or mints an interval.** Both instants and the created instant arrive
from the caller, so a pin written while reproducing a past state is reproducible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.config import PINS_TABLE
from syncr_api.plans.facts import Pin
from syncr_api.plans.records import PinRecord
from syncr_api.plans.stored_documents import read_binding, stored_binding
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.plans.declarations import PinToHold
    from syncr_domain.identifiers import PinId
    from syncr_domain.identity import BindingRef

# The columns the `(tenant_id, block_id)` unique index covers, as the upsert names them.
_IDENTITY = (TENANT_ID_COLUMN, "block_id")

# How many pins one read over a window of weeks returns. A week holds one pin per block and a block
# is fifteen minutes at its shortest, so a quarter cannot reach this; the bound is what stops a
# window read from being unbounded in a deployment nobody expected.
PINS_OVER_A_WINDOW = 2000


class PinRepository(TenantScopedRepository):
    """One tenant's pins: held per block, read per week, released by id or by binding."""

    async def hold(self, pin: PinToHold) -> PinRecord:
        """State where the user put one block, replacing whatever this block's pin said before.

        Returned from the statement that wrote it rather than read back, because the row's identity
        is the block and its primary key is not: a re-pin keeps the row and changes every other
        column, so the caller cannot know the id it ends up with without being told.
        """
        written = await self._session.scalars(
            insert(Pin)
            .values([self._row(pin)])
            .on_conflict_do_update(
                index_elements=list(_IDENTITY),
                set_={
                    "iso_week": str(pin.iso_week),
                    "binding": stored_binding(pin.binding),
                    "starts_at": pin.interval.start,
                    "ends_at": pin.interval.end,
                    "superseded_starts_at": pin.superseded_placement.start,
                    "superseded_ends_at": pin.superseded_placement.end,
                    "objective_delta": None,
                    "weight_set_version": pin.weight_set_version,
                    "created_at": pin.created_at,
                },
            )
            .returning(Pin)
        )
        return _as_record(written.one())

    async def price(self, pin_id: PinId, *, objective_delta: float) -> PinRecord:
        """State what this pin's placement cost, which is what makes the row complete.

        Separate from :meth:`hold` and in the same transaction as it, so the cost a pin stores is a
        property of what commits. **The separation is vestigial**: the caller knows the delta
        before it holds the row, so folding this into the insert would store the cost just as well
        and would close the window in which a row exists without its cost. The row is returned
        rather than the caller reusing what ``hold`` answered: a record carrying a null cost is one
        nothing should read twice.
        """
        written = await self._session.scalars(
            self.scoped_update(Pin)
            .where(Pin.id == pin_id)
            .values(objective_delta=objective_delta)
            .returning(Pin)
        )
        return _as_record(written.one())

    async def find(self, pin_id: PinId) -> PinRecord | None:
        """One pin of this tenant's, or ``None``."""
        found = await self._session.scalar(self.scoped_select(Pin).where(Pin.id == pin_id))
        return None if found is None else _as_record(found)

    async def for_week(self, iso_week: IsoWeek) -> tuple[PinRecord, ...]:
        """Every pin bound to ``iso_week``, in block order.

        Ordered so two reads of one week hand the assembler the same sequence. Nothing derived from
        a pin depends on the order, and a stable one is what makes an assembly reproducible.
        """
        rows = await self._session.scalars(
            self.scoped_select(Pin).where(Pin.iso_week == str(iso_week)).order_by(Pin.block_id)
        )
        return tuple(_as_record(row) for row in rows)

    async def for_weeks(
        self, weeks: Sequence[IsoWeek], *, limit: int = PINS_OVER_A_WINDOW
    ) -> tuple[PinRecord, ...]:
        """Every pin bound to any of ``weeks``, newest week first, bounded.

        One statement for the whole window, because the reader is repeated-pin promotion detection
        and that rule is one pass over pin rows: a read per week would be a read per week to answer
        one question about all of them.

        Newest first, so the bound cuts the oldest weeks rather than the recent end. A pattern is
        about weeks the user has just lived, and a page of the oldest rows could never reach them.
        """
        if not weeks:
            return ()
        rows = await self._session.scalars(
            self.scoped_select(Pin)
            .where(Pin.iso_week.in_([str(one) for one in weeks]))
            .order_by(Pin.iso_week.desc(), Pin.block_id)
            .limit(limit)
        )
        return tuple(_as_record(row) for row in rows)

    async def release(self, pin_id: PinId) -> bool:
        """Stop this pin constraining its week, and report whether a row was holding it.

        The row goes and its ``edit_events`` row stays, which is what "the removed pin's record is
        retained as training data" means: the event carries the pair, the delta and the weight set
        version, so the label the learning layer fits on is untouched by a release.
        """
        return await self._affected_rows(self.scoped_delete(Pin).where(Pin.id == pin_id)) > 0

    async def release_binding(self, iso_week: IsoWeek, binding: BindingRef) -> bool:
        """Release whatever pin holds this content in this week, if one does.

        Stated over the binding rather than over a pin id because the caller that needs it is a
        conflict resolution: it knows which content has to become movable and holds no pin id at
        all. Answering ``False`` is not an error -- anything else may have released the pin since.
        """
        return (
            await self._affected_rows(
                self.scoped_delete(Pin).where(
                    Pin.iso_week == str(iso_week), Pin.binding == stored_binding(binding)
                )
            )
            > 0
        )

    def _row(self, pin: PinToHold) -> dict[str, object]:
        return {
            "id": uuid4(),
            TENANT_ID_COLUMN: self.tenant_id,
            "iso_week": str(pin.iso_week),
            "block_id": pin.block_id,
            "binding": stored_binding(pin.binding),
            "starts_at": pin.interval.start,
            "ends_at": pin.interval.end,
            "superseded_starts_at": pin.superseded_placement.start,
            "superseded_ends_at": pin.superseded_placement.end,
            "objective_delta": None,
            "weight_set_version": pin.weight_set_version,
            "created_at": pin.created_at,
        }


def _as_record(row: Pin) -> PinRecord:
    """One stored row as the frozen view, with its identity and its two spans rebuilt.

    The binding is parsed through the reader a stored document uses, so a row written past this
    repository names the same identity a block does or is refused where it is read.
    """
    return PinRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        iso_week=IsoWeek.parse(row.iso_week),
        block_id=row.block_id,
        binding=read_binding(row.binding, field=f"{PINS_TABLE}.binding"),
        interval=Interval(row.starts_at, row.ends_at),
        superseded_placement=Interval(row.superseded_starts_at, row.superseded_ends_at),
        objective_delta=row.objective_delta,
        weight_set_version=row.weight_set_version,
        created_at=row.created_at,
    )
