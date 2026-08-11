"""The wire shapes the outcome and day routes exchange.

Explicit schemas rather than mapped rows, so a column added to a table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Three properties are stated in the field descriptions as well as here, because the descriptions
reach the OpenAPI document and therefore the caller.

**A recording body names the week the block belongs to.** A block id is a digest of the week and
the binding, so the week cannot be recovered from the id, and the alternative to naming it is a
walk over every revision the tenant has stored to find one block. That walk is the read this
route's 100 ms budget cannot afford, and it would grow with the account's age.

**The two carried halves are in one body rather than two shapes.** A discriminated union over five
states would generate five TypeScript types for one concept. The figure a state does not name is
refused instead, so a body carrying both cannot resolve to whichever the state happens to read.

**Every figure the header renders comes from the server.** The block count, how many are presumed,
and how many days are unconfirmed are all computed here, so the strip on the Week screen and the
header on Today cannot disagree about the same figure.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Annotated

from pydantic import ConfigDict, Field

from syncr_api.core.schemas import WireInstant, WireModel
from syncr_api.outcomes.config import (
    FROM_FIELD,
    MAX_ACTUAL_MINUTES,
    MAX_CONFIRM_RANGE_DAYS,
    TO_FIELD,
    UNCONFIRMED_LOOKBACK_DAYS,
)

# Both reach the wire as enum values, so pydantic resolves them at runtime.
from syncr_domain.identity import Origin  # noqa: TC001
from syncr_domain.outcomes import MIN_ACTUAL_MINUTES, OutcomeState

_STATE_DESCRIPTION = (
    "What happened to the block. `partial` requires `actualMinutes` and `moved` requires "
    "`actualInterval`; every other state refuses both. `presumed` is the state a block already "
    "holds with no user action, so recording it explicitly says only that nothing else happened."
)
_MINUTES_DESCRIPTION = (
    "How many minutes the block really took, for a `partial` outcome only. This is the sole "
    f"source of the duration-estimate signal. At least {MIN_ACTUAL_MINUTES}, because a partial of "
    "no minutes is a skip and has its own state."
)
_INTERVAL_DESCRIPTION = (
    "When the block really happened, for a `moved` outcome only. It creates no pin: a `moved` "
    "outcome describes the past, and a pin constrains the future. At most "
    f"{MAX_ACTUAL_MINUTES} minutes long, for the reason `actualMinutes` carries the same bound."
)
_WEEK_DESCRIPTION = (
    "The ISO week the block belongs to, such as `2026-W07`. A block id is a digest of the week and "
    "the content it holds, so the week cannot be read back out of the id."
)
_UNCONFIRMED_DESCRIPTION = (
    "How many past days hold blocks and have not been confirmed, over the last "
    f"{UNCONFIRMED_LOOKBACK_DAYS} days. A day older than that window can still be confirmed by "
    "naming it; the window bounds the count rather than the act."
)

type ActualMinutes = Annotated[int, Field(ge=MIN_ACTUAL_MINUTES, le=MAX_ACTUAL_MINUTES)]


class TimeRangeBody(WireModel):
    """A half-open span of instants, as a request body carries one."""

    model_config = ConfigDict(extra="forbid")

    start: WireInstant = Field(description="When it began. Carries a UTC offset.")
    end: WireInstant = Field(description="When it ended, excluded. Carries a UTC offset.")


class TimeRangeResponse(WireModel):
    """A half-open span of instants, as a response carries one."""

    start: WireInstant
    end: WireInstant


class OutcomeRequest(WireModel):
    """What the user says happened to one block."""

    model_config = ConfigDict(extra="forbid")

    iso_week: str = Field(description=_WEEK_DESCRIPTION)
    state: OutcomeState = Field(description=_STATE_DESCRIPTION)
    actual_minutes: ActualMinutes | None = Field(default=None, description=_MINUTES_DESCRIPTION)
    actual_interval: TimeRangeBody | None = Field(default=None, description=_INTERVAL_DESCRIPTION)


class OutcomeResponse(WireModel):
    """One block's outcome, as the log now holds it."""

    block_id: str
    state: OutcomeState
    actual_minutes: int | None
    actual_interval: TimeRangeResponse | None
    occurred_at: WireInstant = Field(description="When the block was scheduled.")
    confirmed_at: WireInstant | None = Field(
        default=None,
        description=(
            "When the day this block belongs to was confirmed. Null means the day is "
            "unconfirmed, which excludes it from reviews and from learning. Recording an "
            "outcome does not confirm a day, and correcting one does not move this instant."
        ),
    )


class LedgerRowResponse(WireModel):
    """One row of the day, in the order the ledger renders its columns."""

    block_id: str
    interval: TimeRangeResponse
    duration_minutes: int
    area_id: str | None = Field(
        description="The Area this block is charged to. Null for the frame and for an anchor."
    )
    area_name: str | None = Field(
        description="The Area's name, or null when the block carries no Area or the Area is gone."
    )
    title: str
    origin: Origin = Field(
        description=(
            "What the block is to the reader. `prep` and `transit` are blocks like any other: "
            "they appear here, they can be confirmed, and they carry outcomes."
        )
    )
    outcome: OutcomeResponse | None = Field(
        description=(
            "What the log says happened, or null when nothing has been recorded. Null reads as "
            "`presumed` and unconfirmed: a block is presumed complete unless the user says "
            "otherwise, so the absent row is the ordinary case."
        )
    )


class DayResponse(WireModel):
    """One day's ledger: the header figures, and the rows in two sections."""

    date: date
    zone: str = Field(description="The zone this day's bounds were resolved in.")
    span: TimeRangeResponse = Field(
        description=(
            "The instants the day covers. 23 or 25 hours long on a daylight-saving transition "
            "date, and any length at all across a travel boundary."
        )
    )
    block_count: int
    presumed_count: int = Field(
        description="How many of the day's blocks nobody has said anything about."
    )
    confirmed_at: WireInstant | None = Field(
        description=(
            "When the day was confirmed, or null when at least one of its blocks has not been "
            "answered for. A day holding no block is never confirmed and is never counted as "
            "unconfirmed: there is nothing to answer for."
        )
    )
    unconfirmed_days: int = Field(description=_UNCONFIRMED_DESCRIPTION)
    behind: list[LedgerRowResponse] = Field(
        description="The blocks that have ended, earliest first."
    )
    ahead: list[LedgerRowResponse] = Field(
        description=(
            "The blocks that have not ended, earliest first. A block still running is here: it "
            "has not happened yet, so it is presumed until the user says otherwise."
        )
    )


class ConfirmRangeRequest(WireModel):
    """Which past days to settle in one call."""

    model_config = ConfigDict(extra="forbid")

    from_: date = Field(alias=FROM_FIELD, description="The first date to confirm, included.")
    to: date = Field(
        alias=TO_FIELD,
        description=(
            "The last date to confirm, included. At most "
            f"{MAX_CONFIRM_RANGE_DAYS} days after the first."
        ),
    )


class ConfirmRangeResponse(WireModel):
    """What a backfill settled, so the control can say how many."""

    confirmed_days: int = Field(
        description=(
            "How many days this call settled. A day already confirmed, a day holding no block, "
            "and a date that does not exist in the tenant's zone are each not counted."
        )
    )
    blocks_recorded: int = Field(
        description="How many blocks the call answered for across those days."
    )
    unconfirmed_days: int = Field(description=_UNCONFIRMED_DESCRIPTION)
