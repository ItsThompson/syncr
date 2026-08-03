"""The calendar-source service: what a route may ask, and the rules each answer is subject to.

The role rules and the horizon rule live in :mod:`syncr_api.calendars.rules`, because each is an
invariant of the domain rather than a step in a request. What is decided here is the ordering:
which read happens before which write, and which mutation invalidates a solve.

**One write target per tenant.** The read below is a courtesy that produces a stated 409; the
partial unique index is the guarantee. A caller racing another is rejected by the index rather
than by the read, which is why the read does not have to hold a lock.

**Extending the horizon invalidates the weeks it newly covers.** A week whose inputs now include
a projection bound has to be re-solved for the plan to reach the phone, so the input version of
every week the new range covers is bumped.

**A forced sync is an operation.** ``POST .../sync`` answers with one because a feed read is
network-bound and the caller needs something to follow.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row these
methods touch came from a repository scoped to the principal's own tenant, so the scoped
``SELECT`` is what turns another tenant's identifier into a 404; the explicit call is defense in
depth, at the only place an unscoped read could be introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    HORIZON_DAYS_DEFAULT,
    ICS,
    SOURCE_RESOURCE,
    WRITE_TARGET,
)
from syncr_api.calendars.rules import (
    require_a_projectable_horizon,
    require_a_readable_provider,
    require_no_anchor_history,
    require_no_write_target,
    require_the_write_target,
)
from syncr_api.calendars.urls import normalize_feed_url
from syncr_api.core.errors import Conflict, NotFound
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.user_settings.solve_inputs import weeks_covering
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.calendars.config import CalendarProvider
    from syncr_api.calendars.records import CalendarSourceId, CalendarSourceRecord
    from syncr_api.calendars.repository import CalendarSourceRepository
    from syncr_api.calendars.sync import SourceSyncer
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.solving.records import OperationRecord
    from syncr_api.user_settings.solve_inputs import WeekInputVersions

_log = get_logger("syncr.calendars")


@dataclass(frozen=True, slots=True)
class NewSource:
    """What one ``POST`` asked to add.

    ``role`` is absent deliberately. A source is added as an anchor source and promoted through
    ``PUT .../role``, so adding a calendar and handing syncr destructive write access to it are
    two acts the user takes separately.
    """

    provider: CalendarProvider
    display_name: str
    external_id: str


@dataclass(frozen=True, slots=True)
class SourceChange:
    """What one ``PATCH`` asked to change. ``None`` means leave the value alone."""

    included: bool | None = None
    display_name: str | None = None


class CalendarSourceService:
    """Add, read, change, sync, and remove one tenant's calendar sources."""

    def __init__(
        self,
        sources: CalendarSourceRepository,
        syncer: SourceSyncer,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._sources = sources
        self._syncer = syncer
        self._versions = versions
        self._clock = clock

    @measured("calendars")
    async def list_sources(self, principal: Principal) -> tuple[CalendarSourceRecord, ...]:
        """Every source this tenant has, oldest first, each with its sync state."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._sources.list_all()

    @measured("calendars")
    async def read_source(
        self, principal: Principal, source_id: CalendarSourceId
    ) -> CalendarSourceRecord:
        """One source, or a 404 that discloses nothing about another tenant's rows."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._found(principal, source_id)

    @measured("calendars")
    async def add_source(self, principal: Principal, new: NewSource) -> CalendarSourceRecord:
        """Add an anchor source, with its external identifier normalized.

        An ICS feed URL is normalized before it is stored, so the address a user reads back is
        the address syncr fetches. A Google calendarId is taken as given: it is the provider's
        own opaque identifier, and rewriting it would break the read.
        """
        require_scope(principal, Scope.ADMIN)
        external_id = (
            normalize_feed_url(new.external_id) if new.provider == ICS else new.external_id.strip()
        )
        if await self._sources.find_by_external_id(new.provider, external_id) is not None:
            raise Conflict(
                "That calendar is already a source, so it was not added again. Adding it twice "
                "would count every commitment on it twice. The source already configured still "
                "syncs."
            )
        created = await self._sources.create(
            provider=new.provider,
            role=ANCHOR_SOURCE,
            display_name=new.display_name.strip(),
            external_id=external_id,
            included=True,
            horizon_days=None,
            created_at=self._clock(),
        )
        _log.info(
            "calendars.source.added",
            tenant_id=str(principal.tenant_id),
            source_id=str(created.id),
            provider=created.provider,
        )
        return created

    @measured("calendars")
    async def change_source(
        self, principal: Principal, source_id: CalendarSourceId, change: SourceChange
    ) -> CalendarSourceRecord:
        """Include or exclude a source, and optionally rename it.

        Excluding one reports zero anchors immediately rather than at the next poll, which is
        what the read model's excluded state renders. Nothing is deleted: including it again
        restores the count on the next successful sync.
        """
        require_scope(principal, Scope.ADMIN)
        found = await self._found(principal, source_id)
        included = found.included if change.included is None else change.included
        await self._sources.set_inclusion(
            source_id, included=included, display_name=_renamed(change.display_name)
        )
        _log.info(
            "calendars.source.changed",
            tenant_id=str(principal.tenant_id),
            source_id=str(source_id),
            included=included,
        )
        return await self._found(principal, source_id)

    @measured("calendars")
    async def designate_write_target(
        self, principal: Principal, source_id: CalendarSourceId
    ) -> CalendarSourceRecord:
        """Give one source the write-target role, or state why it cannot have it."""
        require_scope(principal, Scope.ADMIN)
        found = await self._found(principal, source_id)
        if found.role == WRITE_TARGET:
            return found
        require_no_anchor_history(found)
        require_no_write_target(await self._sources.write_target())

        await self._sources.designate_write_target(source_id, horizon_days=HORIZON_DAYS_DEFAULT)
        _log.info(
            "calendars.write_target.designated",
            tenant_id=str(principal.tenant_id),
            source_id=str(source_id),
            horizon_days=HORIZON_DAYS_DEFAULT,
        )
        return await self._found(principal, source_id)

    @measured("calendars")
    async def set_horizon(
        self, principal: Principal, source_id: CalendarSourceId, *, horizon_days: int
    ) -> CalendarSourceRecord:
        """Set how many days ahead the plan is projected. Write-target only."""
        require_scope(principal, Scope.ADMIN)
        found = await self._found(principal, source_id)
        require_the_write_target(found)
        require_a_projectable_horizon(horizon_days)

        await self._sources.set_horizon(source_id, horizon_days=horizon_days)
        _log.info(
            "calendars.horizon.changed",
            tenant_id=str(principal.tenant_id),
            source_id=str(source_id),
            horizon_days=horizon_days,
        )
        await self._bump_covered_weeks(horizon_days)
        return await self._found(principal, source_id)

    @measured("calendars")
    async def sync_source(
        self, principal: Principal, source_id: CalendarSourceId
    ) -> OperationRecord:
        """Force one source to sync now, and answer with the operation that did it."""
        require_scope(principal, Scope.ADMIN)
        found = await self._found(principal, source_id)
        require_a_readable_provider(found)
        return await self._syncer.sync_now(found)

    @measured("calendars")
    async def remove_source(self, principal: Principal, source_id: CalendarSourceId) -> None:
        """Remove a source, and with it every anchor that cascades from it."""
        require_scope(principal, Scope.ADMIN)
        await self._found(principal, source_id)
        await self._sources.remove(source_id)
        _log.info(
            "calendars.source.removed",
            tenant_id=str(principal.tenant_id),
            source_id=str(source_id),
        )

    async def _found(
        self, principal: Principal, source_id: CalendarSourceId
    ) -> CalendarSourceRecord:
        found = await self._sources.find(source_id)
        if found is None:
            raise NotFound(f"No {SOURCE_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=SOURCE_RESOURCE)
        return found

    async def _bump_covered_weeks(self, horizon_days: int) -> None:
        """Invalidate every week the new horizon covers, from the current one onwards.

        A shortened horizon bumps the same weeks a lengthened one does. Both change what the
        projection writes, and re-solving a week that is still covered costs one solve while
        missing one leaves the phone showing a plan the horizon no longer includes.
        """
        today = self._clock().date()
        affected = weeks_covering(today, today + timedelta(days=horizon_days), today=today)
        if affected is not None:
            await self._versions.bump(affected)


def _renamed(display_name: str | None) -> str | None:
    """A trimmed new name, or ``None`` when the patch left the name alone.

    A name sent as whitespace is a rename to nothing, which would leave a panel row with no
    label, so it reads as no rename at all.
    """
    if display_name is None:
        return None
    return display_name.strip() or None
