"""What Google's responses are allowed to be, declared rather than assumed.

A provider contract changes under you. So every field syncr reads is declared here with its type
and its optionality, and a response that does not match is a stated failure at the boundary rather
than a ``KeyError`` or a ``None`` three layers into placement.

**Unknown fields are ignored, missing ones are not.** Google adds fields constantly
(``eventType``, ``workingLocationProperties``, ``birthdayProperties``), and refusing an additive
change would turn a Google release into an outage. What is refused is a shape syncr cannot read:
an item with no identifier, a page whose ``items`` is not a list.

**Almost everything on an event is optional, and that is the contract rather than laziness.** An
incremental read returns deleted events carrying ``id`` and ``status`` and nothing else, so a model
that required ``start`` would reject every deletion, which is exactly the silent data loss the
sync token exists to prevent. What each absence MEANS is decided one layer up, in
:mod:`syncr_api.calendars.google_values`.

**Nothing here is a title syncr keeps by accident.** ``summary`` and ``location`` are read because
an anchor needs them; the redaction rule is enforced where lines are written, and every field name
on these models is one the logger's key-name redactor already eats.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# Google's own vocabulary for a deleted event, in both the events collection and the calendar list.
CANCELLED: Final = "cancelled"
# The transparency value that says an event does not consume the user's time.
TRANSPARENT: Final = "transparent"
# The access roles that can write to a calendar, which is what a write target needs.
WRITABLE_ROLES: Final = frozenset({"writer", "owner"})


class GoogleTimePayload(BaseModel):
    """One end of an event: a date, a date-time, or neither.

    All three fields are optional because the three states are meaningful: ``date`` is an all-day
    end, ``dateTime`` is a timed one, and neither is a cancelled event or a shape syncr refuses.
    ``timeZone`` is read and deliberately not used to compute an instant; ``dateTime`` already
    carries its offset, and an all-day span is resolved in the user's own zone.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    date: str | None = None
    date_time: str | None = Field(default=None, alias="dateTime")
    time_zone: str | None = Field(default=None, alias="timeZone")


class GoogleEventPayload(BaseModel):
    """One event as the events collection states it.

    ``id`` is the only required field. With ``singleEvents=true`` an instance of a recurring event
    has its own id that survives the instance being moved, which is what lets a moved occurrence
    keep the identity the unmoved one had.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(min_length=1)
    status: str | None = None
    summary: str | None = None
    location: str | None = None
    transparency: str | None = None
    sequence: int | None = None
    recurring_event_id: str | None = Field(default=None, alias="recurringEventId")
    start: GoogleTimePayload | None = None
    end: GoogleTimePayload | None = None

    @property
    def is_cancelled(self) -> bool:
        """Whether Google says this event no longer occupies any time."""
        return self.status == CANCELLED

    @property
    def is_transparent(self) -> bool:
        """Whether Google says this event does not consume the user's time."""
        return self.transparency == TRANSPARENT


class GoogleEventsPage(BaseModel):
    """One page of an events read, and the two tokens that decide what happens next.

    Exactly one of the tokens is present on any page: another page, or the token to send next
    time. Both are declared optional because a page is allowed to be the last and the first.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    items: list[GoogleEventPayload] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    next_sync_token: str | None = Field(default=None, alias="nextSyncToken")


class GoogleCalendarPayload(BaseModel):
    """One calendar in the account's list, as the calendar list states it."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(min_length=1)
    summary: str | None = None
    time_zone: str | None = Field(default=None, alias="timeZone")
    access_role: str | None = Field(default=None, alias="accessRole")
    primary: bool | None = None
    selected: bool | None = None
    deleted: bool | None = None

    @property
    def is_writable(self) -> bool:
        """Whether this account may write to this calendar, which a write target must."""
        return self.access_role in WRITABLE_ROLES


class GoogleCalendarListPage(BaseModel):
    """One page of the account's calendar list."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    items: list[GoogleCalendarPayload] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class GoogleErrorPayload(BaseModel):
    """The error body's reason, which is what distinguishes a rate limit from a scope problem.

    Google nests it: ``{"error": {"code": 403, "errors": [{"reason": "rateLimitExceeded"}]}}``.
    The status alone cannot tell a rate limit from an insufficient grant, and those two send the
    user to different repairs.
    """

    model_config = ConfigDict(extra="ignore")

    error: GoogleErrorBody | None = None

    @property
    def reasons(self) -> tuple[str, ...]:
        """Every reason the body states, or nothing when it states none."""
        if self.error is None:
            return ()
        return tuple(detail.reason for detail in self.error.errors if detail.reason)


class GoogleErrorDetail(BaseModel):
    """One reason inside an error body."""

    model_config = ConfigDict(extra="ignore")

    reason: str | None = None
    message: str | None = None


class GoogleErrorBody(BaseModel):
    """The error object itself: a code, a message, and the reasons behind it."""

    model_config = ConfigDict(extra="ignore")

    code: int | None = None
    message: str | None = None
    errors: list[GoogleErrorDetail] = Field(default_factory=list)


GoogleErrorPayload.model_rebuild()
