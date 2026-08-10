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
    DISPLAY_NAME_MAX_LENGTH,
    EXTERNAL_ID_MAX_LENGTH,
    HORIZON_DAYS_MAX,
    HORIZON_DAYS_MIN,
    WRITE_TARGET,
    CalendarProvider,
    CalendarRole,
    RejectionKind,
    SourceState,
)
from syncr_api.core.notices import Notice  # noqa: TC001 - pydantic resolves annotations at runtime
from syncr_api.core.schemas import WireModel

if TYPE_CHECKING:
    from syncr_api.calendars.events import RemoteCalendar
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
_ATTEMPTS_DESCRIPTION = (
    "How many calls the last attempt made. More than one means the provider rate-limited the read "
    "and syncr backed off, which is a different story from a slow feed."
)
_RESYNC_DESCRIPTION = (
    "Why the last successful read was a full one while an incremental cursor was held. Null when "
    "the read was incremental, or when there was no cursor to be incremental against."
)

# What the write-target read model states, verbatim, because the destructive behaviour has to be
# stated plainly wherever the role is shown rather than only in the copy of one screen.
DESTRUCTIVE_RECONCILIATION = (
    "syncr owns this calendar and reconciles it destructively: over the projection horizon it "
    "removes anything it did not put there, so an event you add or drag in a calendar client is "
    "overwritten on the next write. Edit the plan in syncr, not here."
)
RECONCILIATION_KIND = "destructive"


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
    attempts: int = Field(default=0, description=_ATTEMPTS_DESCRIPTION)
    resync_reason: str | None = Field(default=None, description=_RESYNC_DESCRIPTION)


class WriteTargetResponse(WireModel):
    """What the one calendar syncr writes to is, and what syncr does to it.

    Present only on the source holding the role. It exists so the destructive behaviour is part of
    the READ MODEL rather than copy on one screen: whatever renders the write target renders this,
    and a second surface cannot forget to say it.
    """

    calendar_name: str = Field(description="The calendar syncr writes the plan to.")
    horizon_days: int = Field(
        description="How many days ahead the plan is written, and past which nothing is removed."
    )
    reconciliation: str = Field(
        description="How syncr makes the calendar match the plan. Always 'destructive'."
    )
    statement: str = Field(description="The destructive behaviour, in words a reader can act on.")

    @classmethod
    def of(cls, record: CalendarSourceRecord) -> Self | None:
        """The write-target reading of a source, or ``None`` when it does not hold the role."""
        if record.role != WRITE_TARGET or record.horizon_days is None:
            return None
        return cls(
            calendar_name=record.display_name,
            horizon_days=record.horizon_days,
            reconciliation=RECONCILIATION_KIND,
            statement=DESTRUCTIVE_RECONCILIATION,
        )


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
    write_target: WriteTargetResponse | None = Field(
        default=None,
        description=(
            "Present only on the source holding the write-target role: what syncr writes to, how "
            "far ahead, and that it reconciles destructively."
        ),
    )

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
                attempts=state.attempts,
                resync_reason=state.resync_reason,
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
            write_target=WriteTargetResponse.of(record),
        )


class RemoteCalendarResponse(WireModel):
    """One calendar an account holds, as the setup surface lists it for selection."""

    calendar_id: str = Field(
        description="The provider's own identifier. This becomes the source's externalId."
    )
    display_name: str
    time_zone: str | None = None
    writable: bool = Field(
        description=(
            "Whether this account may write to the calendar. Only a writable calendar can be the "
            "write target, because syncr reconciles that one destructively."
        )
    )
    primary: bool

    @classmethod
    def of(cls, calendar: RemoteCalendar) -> Self:
        return cls(
            calendar_id=calendar.calendar_id,
            display_name=calendar.display_name,
            time_zone=calendar.time_zone,
            writable=calendar.writable,
            primary=calendar.primary,
        )


class RemoteCalendarsResponse(WireModel):
    """Every calendar the connected account holds, for selection during setup."""

    calendars: list[RemoteCalendarResponse]


class CalendarSourcesResponse(WireModel):
    """Every source this tenant has, oldest first, and every notice their state raises.

    The notices are composed by the api rather than by the screen that renders them, for the reason
    the write-target expiry notices are: the words a reader acts on are written once, so two
    surfaces cannot state one outage differently.
    """

    sources: list[CalendarSourceResponse]
    notices: list[Notice] = Field(
        default_factory=list,
        description=(
            "Every notice this tenant's sources raise. A stale feed raises one amber panel naming "
            "the source and the days it put in doubt, so a surface marks a day without deciding "
            "anything. There is no staleness threshold on this document: the server applies it."
        ),
    )


class AddCalendarSourceRequest(WireModel):
    """Add an anchor source. No OAuth is required for an ICS source."""

    model_config = ConfigDict(extra="forbid")

    provider: CalendarProvider
    display_name: str = Field(min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH)
    external_id: str = Field(
        min_length=1,
        # Bounded at the boundary as well as inside the ICS normalizer, because a Google
        # calendarId is taken as the provider states it and is never normalized: without this a
        # value wider than the column reaches the driver and answers 500 rather than a stated 422.
        max_length=EXTERNAL_ID_MAX_LENGTH,
        description=(
            "A feed address for an ICS source: ics, webcal, http, or https, normalized on the "
            "way in. A calendarId for a Google source, taken as the provider states it."
        ),
    )


class CalendarSourcePatchRequest(WireModel):
    """Include or exclude a source, and optionally rename it. An omitted field is left alone."""

    model_config = ConfigDict(extra="forbid")

    included: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH)


class HorizonPatchRequest(WireModel):
    """Set how many days ahead the plan is projected. Write-target only."""

    model_config = ConfigDict(extra="forbid")

    horizon_days: int = Field(ge=HORIZON_DAYS_MIN, le=HORIZON_DAYS_MAX)
