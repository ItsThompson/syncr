"""The composed week view: one read, and everything the ledger prints from it.

The api answers this whole view in one request because a chatty read would be visibly slow, and
the CLI reads it the same way the screen does. Every duration in it is integer minutes, which is
what ``--json`` emits and what the human renderer formats.

**A week that holds no plan is not an error.** ``live`` is null when the plan-horizon maintainer
has not reached the week, and the api composes the sentence that says so, so the ledger prints
the server's statement rather than inventing a second wording for the same condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Self

from syncr_cli.errors import MalformedResponse
from syncr_cli.wire.operation import Operation
from syncr_cli.wire.plan import PlanDocument
from syncr_cli.wire.reading import (
    JsonMapping,
    instant,
    integer,
    mapping,
    mappings,
    nested,
    optional_nested,
    optional_text,
    text,
)
from syncr_cli.wire.verdict import Verdict
from syncr_domain.intervals import Interval, IntervalError
from syncr_domain.weeks import IsoWeek, IsoWeekError
from syncr_domain.zones import ZoneError, resolve_zone

WEEK_PATH = "week"


@dataclass(frozen=True, slots=True)
class Readings:
    """The figures the summary strip shows. Computed server-side, so no surface re-derives one.

    Six of the eight the response carries. ``oversubscriptionMinutes`` and ``offPlanMinutes``
    explain the denominator on a screen that draws it and the ledger prints neither, so neither
    is read: a member read and not rendered is a claim about the contract with no reader.
    """

    block_count: int
    scheduled_minutes: int
    discretionary_minutes: int
    unallocated_minutes: int
    unconfirmed_days: int
    plan_currency: str

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(
            block_count=integer(payload, "blockCount", path),
            scheduled_minutes=integer(payload, "scheduledMinutes", path),
            discretionary_minutes=integer(payload, "discretionaryMinutes", path),
            unallocated_minutes=integer(payload, "unallocatedMinutes", path),
            unconfirmed_days=integer(payload, "unconfirmedDays", path),
            plan_currency=text(payload, "planCurrency", path),
        )


@dataclass(frozen=True, slots=True)
class WeekView:
    """One week, as a plan, with the reason there is none where there is none."""

    iso_week: IsoWeek
    span: Interval
    zone_by_date: dict[date, str]
    live: PlanDocument | None
    readings: Readings | None
    verdict: Verdict | None
    operation: Operation | None
    empty_statement: str | None
    proposal_count: int
    conflicted_block_ids: frozenset[str]
    payload: JsonMapping

    @classmethod
    def read(cls, body: object) -> Self:
        payload = mapping(body, WEEK_PATH)
        live = optional_nested(payload, "live", WEEK_PATH)
        readings = optional_nested(payload, "readings", WEEK_PATH)
        verdict = optional_nested(payload, "verdict", WEEK_PATH)
        operation = optional_nested(payload, "operation", WEEK_PATH)
        empty = optional_nested(payload, "emptyWeek", WEEK_PATH)
        iso_week = _iso_week(payload)
        return cls(
            iso_week=iso_week,
            span=_span(payload),
            zone_by_date=_zone_by_date(payload, iso_week),
            live=None if live is None else PlanDocument.read(live, f"{WEEK_PATH}.live"),
            readings=None if readings is None else Readings.read(readings, f"{WEEK_PATH}.readings"),
            verdict=None if verdict is None else Verdict.read(verdict, f"{WEEK_PATH}.verdict"),
            operation=(
                None if operation is None else Operation.read(operation, f"{WEEK_PATH}.operation")
            ),
            empty_statement=None if empty is None else text(empty, "statement", "week.emptyWeek"),
            # A week holds one pending-proposal slot, so the count a ledger prints is nought or
            # one. It is a count rather than a boolean because that is what the ledger's line is,
            # and because the slot is what the api answers with.
            proposal_count=0 if payload.get("proposal") is None else 1,
            conflicted_block_ids=_conflicted_block_ids(payload),
            payload=payload,
        )

    @property
    def zones(self) -> tuple[str, ...]:
        """The distinct zones this week is lived in, in date order.

        More than one is a travel week, and the header names all of them: a week is not one zone,
        and printing only the first would make the following days' wall times unexplained.
        """
        named: dict[str, None] = {}
        for on in sorted(self.zone_by_date):
            named.setdefault(self.zone_by_date[on], None)
        return tuple(named)


def _iso_week(payload: JsonMapping) -> IsoWeek:
    raw = text(payload, "isoWeek", WEEK_PATH)
    try:
        return IsoWeek.parse(raw)
    except IsoWeekError as error:
        raise MalformedResponse(
            f"week.isoWeek is {raw!r}, which names no ISO week such as '2026-W07'."
        ) from error


def _span(payload: JsonMapping) -> Interval:
    span = nested(payload, "span", WEEK_PATH)
    start = instant(span, "start", "week.span")
    end = instant(span, "end", "week.span")
    try:
        return Interval(start, end)
    except IntervalError as error:
        raise MalformedResponse(
            f"week.span runs from {start.isoformat()} to {end.isoformat()}, which is not a week."
        ) from error


def _zone_by_date(payload: JsonMapping, iso_week: IsoWeek) -> dict[date, str]:
    """The zone active on each of the week's dates, keyed by the date itself.

    Keyed by ``date`` rather than by the string the wire carries, because every reader of this
    mapping asks a date-shaped question and one parse here is better than one per reader.

    All seven dates are required and every zone is resolved here. The ledger resolves each date's
    own midnights against its own zone, so a mapping missing one has no bounds for that day at
    all; and a machine whose zone database does not hold what the server named cannot render the
    week whatever format it was asked for. Both are refused where the payload is read, so the two
    renderings agree about whether the response is usable.
    """
    raw = nested(payload, "zoneByDate", WEEK_PATH)
    mapped: dict[date, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise MalformedResponse(
                f"week.zoneByDate[{key!r}] is {value!r}, and a zone is named by a string."
            )
        try:
            mapped[date.fromisoformat(key)] = value
        except ValueError as error:
            raise MalformedResponse(
                f"week.zoneByDate is keyed by {key!r}, which is not an ISO date."
            ) from error
        try:
            resolve_zone(value)
        except ZoneError as error:
            raise MalformedResponse(
                f"week.zoneByDate[{key!r}] names {value!r}, which this machine's time-zone "
                "database does not hold. Nothing was changed."
            ) from error
    missing = [on.isoformat() for on in iso_week.dates() if on not in mapped]
    if missing:
        raise MalformedResponse(
            f"week.zoneByDate states no zone for {', '.join(missing)}, and every date of a week "
            "has one. This CLI will not guess a zone for a day."
        )
    return mapped


def _conflicted_block_ids(payload: JsonMapping) -> frozenset[str]:
    """Which blocks a conflict names, so the ledger can print the word beside them.

    A conflict names its block, and an entry that names none is skipped rather than refused: the
    marker is one word on one row, and losing a whole week's ledger over an unreadable conflict
    would be the wrong trade.
    """
    if payload.get("conflicts") is None:
        return frozenset()
    named = {
        block_id
        for entry in mappings(payload, "conflicts", WEEK_PATH)
        if (block_id := optional_text(entry, "blockId", "week.conflicts")) is not None
    }
    return frozenset(named)
