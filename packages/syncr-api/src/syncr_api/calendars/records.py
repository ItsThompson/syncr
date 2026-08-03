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

    @property
    def rejected_count(self) -> int:
        return len(self.rejections)


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
