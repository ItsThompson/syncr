"""One date's ledger, and what the log says happened to a block.

The date, not the week: ``plan show --date`` and ``day confirm`` both answer with this shape,
because confirming a day reads the settled ledger back. Only the members a rendering prints are
read.

**A row with no outcome is the ordinary case, not a gap.** An absent outcome reads as presumed and
unconfirmed: a block is presumed complete unless the user says otherwise, which is why the api
carries null there rather than a row saying nothing happened.

**The Area arrives named.** This response carries the Area's name beside its identifier, so a day's
rows need no second read the way a week's ledger does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Self

from syncr_cli.errors import MalformedResponse
from syncr_cli.wire.reading import (
    JsonMapping,
    instant,
    integer,
    mapping,
    mappings,
    nested,
    optional_instant,
    optional_nested,
    optional_text,
    text,
)
from syncr_domain.intervals import Interval, IntervalError

if TYPE_CHECKING:
    from datetime import datetime

DAY_PATH = "day"
OUTCOME_PATH = "outcome"

# What the Area column holds for a row charged to no Area: the frame, and an imported anchor.
NO_AREA = "--"

# What a row's outcome column reads when the log holds nothing for it.
PRESUMED = "presumed"


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the log says happened to one block, as a recording answers with it."""

    block_id: str
    state: str
    actual_minutes: int | None
    occurred_at: datetime
    confirmed_at: datetime | None
    payload: JsonMapping

    @classmethod
    def read(cls, body: object, path: str = OUTCOME_PATH) -> Self:
        payload = mapping(body, path)
        return cls(
            block_id=text(payload, "blockId", path),
            state=text(payload, "state", path),
            actual_minutes=_optional_minutes(payload, path),
            occurred_at=instant(payload, "occurredAt", path),
            confirmed_at=optional_instant(payload, "confirmedAt", path),
            payload=payload,
        )

    @property
    def statement(self) -> str:
        """This outcome in the words a row prints: the state, and the minutes when it has any."""
        if self.actual_minutes is None:
            return self.state
        return f"{self.state} {self.actual_minutes}m"


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One block of the day, with what the log says about it."""

    block_id: str
    interval: Interval
    duration_minutes: int
    area_name: str
    title: str
    origin: str
    outcome: Outcome | None

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        recorded = optional_nested(payload, "outcome", path)
        return cls(
            block_id=text(payload, "blockId", path),
            interval=_interval(payload, path),
            duration_minutes=integer(payload, "durationMinutes", path),
            area_name=optional_text(payload, "areaName", path) or NO_AREA,
            title=text(payload, "title", path),
            origin=text(payload, "origin", path),
            outcome=None if recorded is None else Outcome.read(recorded, f"{path}.outcome"),
        )

    @property
    def outcome_statement(self) -> str:
        """What the row's last column reads. Presumed where nothing has been recorded."""
        return PRESUMED if self.outcome is None else self.outcome.statement


@dataclass(frozen=True, slots=True)
class DayLedger:
    """One date: the header figures the server computed, and the rows in two sections."""

    on: date
    zone: str
    block_count: int
    presumed_count: int
    confirmed_at: datetime | None
    unconfirmed_days: int
    behind: tuple[LedgerRow, ...]
    ahead: tuple[LedgerRow, ...]
    payload: JsonMapping

    @classmethod
    def read(cls, body: object) -> Self:
        payload = mapping(body, DAY_PATH)
        return cls(
            on=_date(payload),
            zone=text(payload, "zone", DAY_PATH),
            block_count=integer(payload, "blockCount", DAY_PATH),
            presumed_count=integer(payload, "presumedCount", DAY_PATH),
            confirmed_at=optional_instant(payload, "confirmedAt", DAY_PATH),
            unconfirmed_days=integer(payload, "unconfirmedDays", DAY_PATH),
            behind=_rows(payload, "behind"),
            ahead=_rows(payload, "ahead"),
            payload=payload,
        )

    @property
    def rows(self) -> tuple[LedgerRow, ...]:
        """Every row of the day, in time order: what has ended, then what has not."""
        return (*self.behind, *self.ahead)


def _rows(payload: JsonMapping, name: str) -> tuple[LedgerRow, ...]:
    return tuple(
        LedgerRow.read(entry, f"{DAY_PATH}.{name}[{index}]")
        for index, entry in enumerate(mappings(payload, name, DAY_PATH))
    )


def _date(payload: JsonMapping) -> date:
    raw = text(payload, "date", DAY_PATH)
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise MalformedResponse(
            f"day.date is {raw!r}, which is not an ISO date such as '2026-02-10'."
        ) from error


def _interval(payload: JsonMapping, path: str) -> Interval:
    span = nested(payload, "interval", path)
    where = f"{path}.interval"
    start = instant(span, "start", where)
    end = instant(span, "end", where)
    try:
        return Interval(start, end)
    except IntervalError as error:
        raise MalformedResponse(
            f"{where} runs from {start.isoformat()} to {end.isoformat()}, which is not a span. "
            "Every span on this wire is half-open and runs forward."
        ) from error


def _optional_minutes(payload: JsonMapping, path: str) -> int | None:
    """The minutes a partial outcome names, or null for every other state.

    Refused rather than read as absent when it is present and not a whole number, because the
    figure is the sole source of the duration-estimate signal and a coerced one would train on a
    value nobody recorded.
    """
    if payload.get("actualMinutes") is None:
        return None
    return integer(payload, "actualMinutes", path)
