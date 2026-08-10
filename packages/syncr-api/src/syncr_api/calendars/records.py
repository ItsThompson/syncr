"""The immutable views of a calendar-source row and its embedded sync state.

A repository hands back one of these rather than a mapped instance, so a service cannot
trigger a load it did not ask for and nothing downstream can change a row by assignment.

``SyncStateRecord`` is embedded in the source row rather than kept in a table of its own,
because there is exactly one per source and every read of a source wants it: a panel that
showed a provider and an anchor count without a last-sync time would be the silently stale
feed this product exists to make impossible.

``rejections`` is part of the sync state for the same reason. The panel that states how many
events were rejected and why is rendered from a READ of the source, not from the response to
a sync, so a rejection has to survive the attempt that produced it.

``rejections`` is a bounded SAMPLE and ``rejected_total`` is how many there were. A publisher
decides how many components a feed holds, so the list a panel renders cannot be all of them, and
a count read off the list would report a feed that refused fifty thousand components as having
refused fifteen.

``attempts`` and ``resync_reason`` are there because a provider's own behaviour is part of what
the panel reports. A rate-limited read backs off and retries, and the attempt count is what makes
that visible instead of looking like a slow feed; a provider that invalidates an incremental cursor
forces a full read, and the reason it did is worth more than the silent cost.

``state`` is derived rather than stored. Storing it would let a row disagree with the fields
it summarizes, and every combination that produces it is already in the row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from syncr_api.calendars.config import (
    ERROR,
    EXCLUDED,
    NEVER_SYNCED,
    OK,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.config import CalendarProvider, CalendarRole, SourceState
    from syncr_api.calendars.events import RejectedComponent
    from syncr_domain.identifiers import TenantId

type CalendarSourceId = UUID


@dataclass(frozen=True, slots=True)
class SyncStateRecord:
    """What the last attempt on one source did, successful or not.

    Written on EVERY attempt, which is what makes staleness computable: a source whose last
    attempt is recent and whose last success is not is a source that is failing, and the two
    fields are the only way to tell that from a source nobody has polled.
    """

    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    cursor: str | None = None
    events_read: int = 0
    anchors_current: int = 0
    rejections: tuple[RejectedComponent, ...] = ()
    # How many components the last attempt refused, which is not the length of the sample above:
    # the sample is bounded per kind and this is not bounded at all.
    rejected_total: int = 0
    # How many calls the last attempt made. One for a read that worked first time; more when a
    # provider rate-limited it and the read backed off and retried. Exposed on the source because
    # a count that changes is how this product reports progress, and a read that took four calls is
    # a different story from one that took one.
    attempts: int = 0
    # Why the last successful read was a FULL one rather than incremental, when it was not simply
    # the first. A provider that invalidates a sync token silently costs a full read every poll,
    # and a panel that could not say so would report a healthy source doing hidden work.
    resync_reason: str | None = None

    @property
    def rejected_count(self) -> int:
        """How many components the last attempt refused, sampled or not."""
        return self.rejected_total


@dataclass(frozen=True, slots=True)
class CalendarSourceRecord:
    """One calendar source, as persistence knows it."""

    id: CalendarSourceId
    tenant_id: TenantId
    provider: CalendarProvider
    role: CalendarRole
    display_name: str
    external_id: str
    included: bool
    horizon_days: int | None
    # When the user added it. Carried on the record because staleness for a source that has NEVER
    # been read successfully has to be measured from something that does not move, and every other
    # instant on the row does: the last attempt is refreshed by each failed poll, so a feed added
    # with a wrong URL would report one poll interval of staleness forever.
    created_at: datetime
    sync_state: SyncStateRecord = field(default_factory=SyncStateRecord)

    @property
    def state(self) -> SourceState:
        """What this source's panel reports, derived from the fields that decide it.

        An excluded source is ``excluded`` before it is anything else. The user asked for zero
        anchors from it, so a stale error from before the exclusion must not render as a
        failure: that would be syncr reporting a problem the user already resolved.
        """
        if not self.included:
            return EXCLUDED
        if self.sync_state.last_error is not None:
            return ERROR
        if self.sync_state.last_success_at is None:
            return NEVER_SYNCED
        return OK

    @property
    def anchor_count(self) -> int:
        """How many anchors this source currently contributes.

        Zero for an excluded source, whatever the last successful sync read. Excluding a
        source removes its contribution immediately rather than at the next poll, because the
        user's next question after excluding one is whether it stopped counting.
        """
        return 0 if not self.included else self.sync_state.anchors_current
