"""The four outcome and day routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one service
method, and maps the result onto a response shape. No authorization decision and no persistence:
``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from a record, so a column added to a
table cannot reach the wire by sharing a name with a schema field. The record carries an
``Interval`` and the wire carries two instants, which is the one place that pair is taken apart.

Every unsafe method takes the idempotency guard, because a retried recording must not be applied
twice. Two of the three are guarded to a stated limit rather than fully, and the limit is
``block_outcomes``' own identity: a repeat of one recording lands the same row whether or not the
guard replayed it, because a row is keyed by the block and the write states an absolute state
rather than a delta. What the guard adds on top of that is the stored RESPONSE, so a retry after a
timeout reads the same body rather than a body that has moved on.

The date is a path parameter typed as a date, so a malformed one is the framework's own 422 with
the shape every other validation failure has. Nothing here parses a date.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Path

from syncr_api.accounts.injection import ClientPrincipalDep, PrincipalDep
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.outcomes.config import (
    CONFIRM_PATH,
    CONFIRM_RANGE_PATH,
    DAY_PATH,
    OUTCOME_PATH,
)
from syncr_api.outcomes.declarations import Recording
from syncr_api.outcomes.injection import OutcomeServiceDep
from syncr_api.outcomes.schemas import (
    ConfirmRangeRequest,
    ConfirmRangeResponse,
    DayResponse,
    LedgerRowResponse,
    OutcomeRequest,
    OutcomeResponse,
    TimeRangeResponse,
)
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from syncr_api.outcomes.ledger import Backfill, DayLedger, LedgerRow
    from syncr_api.plans.records import BlockOutcomeRecord

blocks_router = APIRouter()
days_router = APIRouter()

RECORD_ROUTE = "outcomes.record_outcome"
CONFIRM_ROUTE = "outcomes.confirm_day"
CONFIRM_RANGE_ROUTE = "outcomes.confirm_range"

_DATE = Path(description="The local date, as `2026-02-09`.")


def _as_range(interval: Interval) -> TimeRangeResponse:
    return TimeRangeResponse(start=interval.start, end=interval.end)


def _as_outcome(record: BlockOutcomeRecord) -> OutcomeResponse:
    return OutcomeResponse(
        block_id=record.block_id,
        state=record.state,
        actual_minutes=record.actual_minutes,
        actual_interval=(
            None if record.actual_interval is None else _as_range(record.actual_interval)
        ),
        occurred_at=record.occurred_at,
        confirmed_at=record.confirmed_at,
    )


def _as_row(row: LedgerRow) -> LedgerRowResponse:
    return LedgerRowResponse(
        block_id=row.block_id,
        interval=_as_range(row.interval),
        duration_minutes=row.duration_minutes,
        area_id=None if row.area_id is None else str(row.area_id),
        area_name=row.area_name,
        title=row.title,
        origin=row.origin,
        outcome=None if row.outcome is None else _as_outcome(row.outcome),
    )


def _as_day(ledger: DayLedger) -> DayResponse:
    return DayResponse(
        date=ledger.on,
        zone=ledger.zone,
        span=_as_range(ledger.span),
        block_count=ledger.block_count,
        presumed_count=ledger.presumed_count,
        confirmed_at=ledger.confirmed_at,
        unconfirmed_days=ledger.unconfirmed_days,
        behind=[_as_row(row) for row in ledger.behind],
        ahead=[_as_row(row) for row in ledger.ahead],
    )


def _as_backfill(backfill: Backfill) -> ConfirmRangeResponse:
    return ConfirmRangeResponse(
        confirmed_days=backfill.days,
        blocks_recorded=backfill.blocks,
        unconfirmed_days=backfill.unconfirmed_days,
    )


@blocks_router.put(OUTCOME_PATH, summary="Record what happened to one block")
async def record_outcome(
    block_id: Annotated[str, Path(description="The block's derived identity.")],
    body: OutcomeRequest,
    principal: ClientPrincipalDep,
    guard: IdempotencyGuardDep,
    service: OutcomeServiceDep,
) -> OutcomeResponse:
    """State `completed`, `partial` with minutes, `skipped`, or `moved` with an interval.

    Recording does not confirm the day. A block marked skipped on a day the user has not answered
    for is a statement about the block, and the day stays excluded from reviews and from learning.
    """
    recording = Recording(
        iso_week=body.iso_week,
        state=body.state,
        actual_minutes=body.actual_minutes,
        actual_interval=(
            None
            if body.actual_interval is None
            else Interval(body.actual_interval.start, body.actual_interval.end)
        ),
    )

    async def record() -> OutcomeResponse:
        return _as_outcome(await service.record(principal, block_id, recording))

    return await guard.once(RECORD_ROUTE, OutcomeResponse, record)


@days_router.get(DAY_PATH, summary="The Today ledger for one date")
async def read_day(
    date: Annotated[date, _DATE], principal: ClientPrincipalDep, service: OutcomeServiceDep
) -> DayResponse:
    """The day's blocks in time order, grouped into what has ended and what has not."""
    return _as_day(await service.read_day(principal, date))


@days_router.post(CONFIRM_PATH, summary="Confirm one day, converting presumption into record")
async def confirm_day(
    date: Annotated[date, _DATE],
    principal: ClientPrincipalDep,
    guard: IdempotencyGuardDep,
    service: OutcomeServiceDep,
) -> DayResponse:
    """Answer for every block of the day, and read the settled ledger back."""

    async def confirm() -> DayResponse:
        return _as_day(await service.confirm_day(principal, date))

    return await guard.once(CONFIRM_ROUTE, DayResponse, confirm)


@days_router.post(CONFIRM_RANGE_PATH, summary="Confirm several past days in one call")
async def confirm_range(
    body: ConfirmRangeRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: OutcomeServiceDep,
) -> ConfirmRangeResponse:
    """Backfill a range of past days, and report how many it settled."""

    async def confirm() -> ConfirmRangeResponse:
        return _as_backfill(await service.confirm_range(principal, body.from_, body.to))

    return await guard.once(CONFIRM_RANGE_ROUTE, ConfirmRangeResponse, confirm)
