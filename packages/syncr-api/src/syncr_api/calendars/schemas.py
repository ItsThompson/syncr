"""The wire shapes the calendar-source routes exchange.

Explicit schemas rather than mapped rows, so a column added to the table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Two properties of the read model are stated in the field descriptions rather than only here,
because the descriptions reach the OpenAPI document and therefore the caller.

**There is no progress field and no percentage.** A count that changes is how progress is
reported in this product: ``anchorCount`` moving from 0 to 61 is the whole signal, and no
spinner or progress bar appears anywhere. A ``progress`` field on this shape would invite one.

**``state`` distinguishes excluded from failed.** An excluded source reports zero anchors because
the user asked it to, and rendering that as an error would report a problem they already
resolved.

``role`` is absent from the add request. A source is added as an anchor source and promoted
through ``PUT .../role``, so adding a calendar and handing syncr destructive write access to it
are two acts the user takes separately. An unknown field is rejected, so sending ``role`` on a
``POST`` is a stated 422 rather than a value quietly ignored.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import ConfigDict, Field

from syncr_api.calendars.config import (
    HORIZON_DAYS_MAX,
    HORIZON_DAYS_MIN,
    CalendarProvider,
    CalendarRole,
    RejectionKind,
    SourceState,
)
from syncr_api.core.schemas import WireModel

if TYPE_CHECKING:
    from syncr_api.calendars.records import CalendarSourceRecord

_STATE_DESCRIPTION = (
    "What this source's panel reports. 'excluded' is not an error: the user asked for zero "
    "anchors from it. 'error' means the last attempt could not read it, and the anchors it "
    "already contributed are retained."
)
_ANCHOR_COUNT_DESCRIPTION = (
    "How many commitments this source currently contributes. A count that changes is how "
    "progress is reported: there is no spinner and no progress bar anywhere in this product."
)
_HORIZON_DESCRIPTION = (
    "How many days ahead the plan is projected onto the write target. Null on an anchor source, "
    "which is read over whatever span the week being assembled needs."
)


class RejectedEventResponse(WireModel):
    """One component of a feed that produced no event, and why."""

    kind: RejectionKind
    line: int = Field(
        description="The line the component began on in the feed as delivered, before unfolding."
    )
    component: str
    detail: str
    uid: str | None = None


class SyncStateResponse(WireModel):
    """What the last attempt on a source did, successful or not.

    Both instants are exposed because staleness is the difference between them: a recent attempt
    with an older success is a source that is failing, and that is not the same as a source
    nobody has polled.
    """

    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = Field(
        default=None,
        description=(
            "Why the last attempt failed, stated with what still works. Null when it succeeded."
        ),
    )
    events_read: int
    rejected_count: int
    rejections: list[RejectedEventResponse]


class CalendarSourceResponse(WireModel):
    """One calendar source, with the reading its Settings panel renders."""

    id: UUID
    provider: CalendarProvider
    role: CalendarRole
    display_name: str
    external_id: str
    included: bool
    horizon_days: int | None = Field(default=None, description=_HORIZON_DESCRIPTION)
    state: SourceState = Field(description=_STATE_DESCRIPTION)
    anchor_count: int = Field(description=_ANCHOR_COUNT_DESCRIPTION)
    sync_state: SyncStateResponse

    @classmethod
    def of(cls, record: CalendarSourceRecord) -> Self:
        """The wire shape of a stored source."""
        state = record.sync_state
        return cls(
            id=record.id,
            provider=record.provider,
            role=record.role,
            display_name=record.display_name,
            external_id=record.external_id,
            included=record.included,
            horizon_days=record.horizon_days,
            state=record.state,
            anchor_count=record.anchor_count,
            sync_state=SyncStateResponse(
                last_success_at=state.last_success_at,
                last_attempt_at=state.last_attempt_at,
                last_error=state.last_error,
                events_read=state.events_read,
                rejected_count=state.rejected_count,
                rejections=[
                    RejectedEventResponse(
                        kind=rejected.kind,
                        line=rejected.line,
                        component=rejected.component,
                        detail=rejected.detail,
                        uid=rejected.uid,
                    )
                    for rejected in state.rejections
                ],
            ),
        )


class CalendarSourcesResponse(WireModel):
    """Every source this tenant has, oldest first."""

    sources: list[CalendarSourceResponse]


class AddCalendarSourceRequest(WireModel):
    """Add an anchor source. No OAuth is required for an ICS source."""

    model_config = ConfigDict(extra="forbid")

    provider: CalendarProvider
    display_name: str = Field(min_length=1, max_length=200)
    external_id: str = Field(
        min_length=1,
        description=(
            "A feed address for an ICS source: ics, webcal, http, or https, normalized on the "
            "way in. A calendarId for a Google source, taken as the provider states it."
        ),
    )


class CalendarSourcePatchRequest(WireModel):
    """Include or exclude a source, and optionally rename it. An omitted field is left alone."""

    model_config = ConfigDict(extra="forbid")

    included: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class HorizonPatchRequest(WireModel):
    """Set how many days ahead the plan is projected. Write-target only."""

    model_config = ConfigDict(extra="forbid")

    horizon_days: int = Field(ge=HORIZON_DAYS_MIN, le=HORIZON_DAYS_MAX)
