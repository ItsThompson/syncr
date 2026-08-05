"""The Today read model: one day's rows in time order, the header figures, and the grouping.

The ledger answers one question, "did this happen", so it is a checklist rather than a
proportional grid, and its shape is the frontend's: a time range, the duration, the Area, the
title, and the current outcome, grouped into what is behind now and what is ahead.

**A block with no outcome row reads as ``presumed`` and unconfirmed.** That is not a gap being
filled in: it is what O1 means. Every block defaults to presumed with no user action, which is what
keeps daily interaction cost near zero, so the absence of a row is the common case rather than the
exceptional one.

**The grouping boundary is the block's END.** A block still running has not been RECORDED yet, so
it sits under the section that says "presumed until you say otherwise" rather than under the one
that says "recorded". This is deliberately NOT the boundary the netting rules use: immovability is
decided on the start, because that rule asks whether the solver may still move the block, and the
two questions have different answers for the same block for as long as it runs.

**A DAY-level confirmation covers the whole day, including the blocks still ahead in it.** The
grouping above is about which section renders a row; confirming is about whether the user has
answered for the day, and they answer for it as a whole. Two reasons, the first decisive:

- A day's last block routinely ends on the NEXT day. A ``Sleep`` routine from 23:00 to 07:00 belongs
  to the day it begins in, so a rule that waited for every block to end would make today
  unconfirmable until tomorrow morning, for every user who sleeps. The evening pass the product is
  designed around would settle nothing.
- Presuming a block that has not happened is what O1 already does for every block, all day.
  Confirming says the user has nothing to add, and if the evening turns out otherwise they record an
  exception and everything projected from the log re-derives, which is O5.

So a confirmed ``presumed`` row on a block later today reads as a completion, and that is the
presumption the product is built on rather than a gap in it.

**A day is settled when every block of it carries a confirmation.** A day holding no block is
neither settled nor unsettled: there is nothing to answer for, so it is not counted among the
unconfirmed days and confirming it stores nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.outcomes import OutcomeState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_api.plans.records import BlockOutcomeRecord
    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BlockId, Origin
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.plan import Block
    from syncr_domain.zones import Date, ZoneId


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerRow:
    """One block of a day, and what the log says happened to it.

    ``outcome`` is ``None`` when no row exists, which the reader renders as ``presumed`` and
    unconfirmed rather than as an absence. Keeping it nullable here rather than fabricating a row
    is what stops a read from looking like a write.
    """

    block_id: BlockId
    interval: Interval
    duration_minutes: int
    area_id: AreaId | None
    area_name: str | None
    title: str
    origin: Origin
    outcome: BlockOutcomeRecord | None

    @property
    def state(self) -> OutcomeState:
        """What this row currently says happened, which is ``presumed`` until it says otherwise."""
        return OutcomeState.PRESUMED if self.outcome is None else self.outcome.state

    @property
    def is_confirmed(self) -> bool:
        """Whether the day this row belongs to has been answered for."""
        return self.outcome is not None and self.outcome.is_confirmed


@dataclass(frozen=True, slots=True, kw_only=True)
class DayLedger:
    """One day, as the Today surface renders it.

    ``behind`` and ``ahead`` partition the day's rows rather than filtering it twice, so the two
    sections cannot both hold one block or leave one out.
    """

    on: Date
    zone: ZoneId
    span: Interval
    behind: tuple[LedgerRow, ...]
    ahead: tuple[LedgerRow, ...]
    confirmed_at: datetime | None
    unconfirmed_days: int

    @property
    def rows(self) -> tuple[LedgerRow, ...]:
        """Every row of the day, in time order."""
        return (*self.behind, *self.ahead)

    @property
    def block_count(self) -> int:
        """How many blocks the day holds, which is what the header states first."""
        return len(self.rows)

    @property
    def presumed_count(self) -> int:
        """How many of them nobody has said anything about, which is the header's second figure."""
        return sum(1 for row in self.rows if row.state is OutcomeState.PRESUMED)


def ledger_rows(
    blocks: Sequence[Block],
    *,
    outcomes: Mapping[BlockId, BlockOutcomeRecord],
    area_names: Mapping[AreaId, str],
) -> tuple[LedgerRow, ...]:
    """The day's blocks paired with whatever the log says about each, in the order given.

    An Area with no name is not an error. A block whose Area was deleted keeps its identifier, and
    the row still renders: an outcome is a fact about a week that happened, and so is the row it
    was recorded against.
    """
    return tuple(
        LedgerRow(
            block_id=block.id,
            interval=block.interval,
            duration_minutes=block.interval.total_minutes(),
            area_id=block.area_id,
            area_name=None if block.area_id is None else area_names.get(block.area_id),
            title=block.title,
            origin=block.origin,
            outcome=outcomes.get(block.id),
        )
        for block in blocks
    )


def split_at(
    rows: Sequence[LedgerRow], now: Instant
) -> tuple[tuple[LedgerRow, ...], tuple[LedgerRow, ...]]:
    """The rows behind ``now`` and the rows ahead of it, in that order.

    A block is behind once it has ENDED. While it runs it is neither recorded nor answerable, and
    the section it belongs in is the one that presumes it.
    """
    behind = tuple(row for row in rows if row.interval.end <= now)
    ahead = tuple(row for row in rows if row.interval.end > now)
    return (behind, ahead)


def settled_at(recorded: Sequence[BlockOutcomeRecord | None]) -> datetime | None:
    """When the day these blocks belong to was answered for, or ``None`` when it has not been.

    Taken over one entry per BLOCK, ``None`` where the log holds nothing for it, because that is
    what makes one statement of this rule serve both callers: the ledger has the row beside each
    block, and the count of outstanding days has only the log keyed by block. A projection of
    either shape reaches this the same way, so the two cannot come to disagree about whether a day
    is settled.

    The EARLIEST confirmation, because that is when the user answered for the day. A block added by
    a later re-solve and confirmed afterwards does not move that instant; it does leave the day
    unsettled until it too is confirmed, which is correct: a block nobody has answered for is a
    block nobody has answered for.
    """
    stamps = [
        one.confirmed_at for one in recorded if one is not None and one.confirmed_at is not None
    ]
    if not recorded or len(stamps) < len(recorded):
        return None
    return min(stamps)


def is_unconfirmed(recorded: Sequence[BlockOutcomeRecord | None]) -> bool:
    """Whether this day holds blocks and has not been answered for.

    A day with no block is neither: there is nothing to answer for, so counting it would report a
    backlog of days on which the user had nothing planned.
    """
    return bool(recorded) and settled_at(recorded) is None


@dataclass(frozen=True, slots=True, kw_only=True)
class Backfill:
    """What one backfill settled, so the control that offered it can say how many.

    ``days`` counts the days this call answered for, which is not the number of dates it was given:
    a day already confirmed, a day holding no block, and a date that does not exist in the tenant's
    zone are each passed over. ``blocks`` is the rows the call stamped, which is the figure the
    write itself reports.
    """

    days: int
    blocks: int
    unconfirmed_days: int
