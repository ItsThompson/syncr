"""Persistence for ``calendar_sources``. Tenant-scoped, and the only writer of sync state.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant.

Two methods are worth reading twice.

``designate_write_target`` does not check first. The partial unique index is the invariant, so
the statement is issued and the database rejects a second write target; a caller that wants a
stated 409 rather than an integrity error reads :meth:`write_target` before calling, and the
index is what makes that read a check rather than the whole guarantee.

``save_sync_state`` writes all seven fields together. An attempt produces one state, and a
field-by-field update would let a crash between two writes leave a source that succeeded and
still carries an error.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`; the worker opens its own around a tick.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from syncr_api.calendars.config import ANCHOR_SOURCE, WRITE_TARGET
from syncr_api.calendars.events import RejectedComponent
from syncr_api.calendars.models import CalendarSource
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.core.repository import TenantScopedRepository

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.config import CalendarProvider, CalendarRole
    from syncr_api.calendars.models import RejectionRow
    from syncr_api.calendars.records import CalendarSourceId


class CalendarSourceRepository(TenantScopedRepository):
    """One tenant's calendar sources, and the sync state embedded in each."""

    async def list_all(self) -> tuple[CalendarSourceRecord, ...]:
        """Every source this tenant has, oldest first."""
        found = await self._session.scalars(
            self.scoped_select(CalendarSource).order_by(
                CalendarSource.created_at, CalendarSource.id
            )
        )
        return tuple(_as_record(row) for row in found)

    async def find(self, source_id: CalendarSourceId) -> CalendarSourceRecord | None:
        """One source of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden, which
        is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(
            self.scoped_select(CalendarSource).where(CalendarSource.id == source_id)
        )
        return _as_record(found) if found is not None else None

    async def find_by_external_id(
        self, provider: CalendarProvider, external_id: str
    ) -> CalendarSourceRecord | None:
        """This tenant's source for one provider's identifier, or ``None``.

        Read before an add so a duplicate is a stated 409 rather than an integrity error. The
        unique index is still the guarantee: two adds racing are rejected by it.
        """
        found = await self._session.scalar(
            self.scoped_select(CalendarSource).where(
                CalendarSource.provider == provider, CalendarSource.external_id == external_id
            )
        )
        return _as_record(found) if found is not None else None

    async def write_target(self) -> CalendarSourceRecord | None:
        """The source holding the write-target role, or ``None``."""
        found = await self._session.scalar(
            self.scoped_select(CalendarSource).where(CalendarSource.role == WRITE_TARGET)
        )
        return _as_record(found) if found is not None else None

    async def included_for(self, provider: CalendarProvider) -> tuple[CalendarSourceRecord, ...]:
        """This tenant's included anchor sources of one provider, oldest first.

        Excluded sources are absent rather than filtered by the caller: the user asked for zero
        anchors from them, so a poll would spend a request to produce a number the read model
        discards. The write target is absent too, because reading back the projection would
        make every solve treat the previous solve's output as immovable commitments.
        """
        found = await self._session.scalars(
            self.scoped_select(CalendarSource)
            .where(
                CalendarSource.provider == provider,
                CalendarSource.role == ANCHOR_SOURCE,
                CalendarSource.included.is_(True),
            )
            .order_by(CalendarSource.created_at, CalendarSource.id)
        )
        return tuple(_as_record(row) for row in found)

    async def create(
        self,
        *,
        provider: CalendarProvider,
        role: CalendarRole,
        display_name: str,
        external_id: str,
        included: bool,
        horizon_days: int | None,
        created_at: datetime,
    ) -> CalendarSourceRecord:
        """Persist one source. The caller has already normalized the external identifier."""
        row = CalendarSource(
            id=uuid4(),
            tenant_id=self.tenant_id,
            provider=provider,
            role=role,
            display_name=display_name,
            external_id=external_id,
            included=included,
            horizon_days=horizon_days,
            events_read=0,
            anchors_current=0,
            created_at=created_at,
        )
        self._session.add(row)
        # Flushed here so a duplicate feed or a second write target surfaces as this call's
        # failure rather than at commit, after the caller has reported success.
        await self._session.flush()
        return _as_record(row)

    async def set_inclusion(
        self, source_id: CalendarSourceId, *, included: bool, display_name: str | None
    ) -> None:
        """Include or exclude a source, and optionally rename it.

        One statement for both, because ``PATCH`` on a source is one request: applying them
        separately would let a rename land while an exclusion did not.
        """
        values: dict[str, object] = {"included": included}
        if display_name is not None:
            values["display_name"] = display_name
        await self._session.execute(
            self.scoped_update(CalendarSource)
            .where(CalendarSource.id == source_id)
            .values(**values)
        )

    async def set_horizon(self, source_id: CalendarSourceId, *, horizon_days: int) -> None:
        """Set the projection horizon on a source. The caller has confirmed it is the target."""
        await self._session.execute(
            self.scoped_update(CalendarSource)
            .where(CalendarSource.id == source_id)
            .values(horizon_days=horizon_days)
        )

    async def designate_write_target(
        self, source_id: CalendarSourceId, *, horizon_days: int
    ) -> None:
        """Give a source the write-target role, with a projection horizon.

        The horizon is set in the same statement because the schema requires the two together:
        a write target always carries a bound past which it will not delete, and an anchor
        source never carries one.
        """
        await self._session.execute(
            self.scoped_update(CalendarSource)
            .where(CalendarSource.id == source_id)
            .values(role=WRITE_TARGET, horizon_days=horizon_days)
        )
        await self._session.flush()

    async def save_sync_state(self, source_id: CalendarSourceId, state: SyncStateRecord) -> None:
        """Record what an attempt on this source did. Called on every attempt, either way."""
        await self._session.execute(
            self.scoped_update(CalendarSource)
            .where(CalendarSource.id == source_id)
            .values(
                last_success_at=state.last_success_at,
                last_attempt_at=state.last_attempt_at,
                last_error=state.last_error,
                cursor=state.cursor,
                events_read=state.events_read,
                anchors_current=state.anchors_current,
                rejections=_as_rows(state.rejections),
            )
        )

    async def remove(self, source_id: CalendarSourceId) -> None:
        """Delete one source of this tenant's."""
        await self._session.execute(
            self.scoped_delete(CalendarSource).where(CalendarSource.id == source_id)
        )


def _as_rows(rejections: tuple[RejectedComponent, ...]) -> list[RejectionRow] | None:
    """The rejections as stored JSONB, or SQL NULL when there were none.

    ``None`` rather than an empty array, so "this attempt rejected nothing" and "nothing has
    been attempted" read the same in the column and the panel decides from the sync instants
    instead of from an empty list nobody wrote.
    """
    return [asdict(rejected) for rejected in rejections] or None


def _from_rows(rows: list[RejectionRow] | None) -> tuple[RejectedComponent, ...]:
    """The stored rejections, back as value objects.

    An unknown key is dropped rather than raising. The column is JSONB, so a row written by an
    older revision of this shape is possible, and refusing to read a source's panel because a
    historical rejection carried a field this code no longer names would be the wrong trade.
    """
    fields = RejectedComponent.__dataclass_fields__
    return tuple(
        RejectedComponent(**{key: value for key, value in row.items() if key in fields})
        for row in rows or []
    )


def _as_record(row: CalendarSource) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        provider=cast("CalendarProvider", row.provider),
        role=cast("CalendarRole", row.role),
        display_name=row.display_name,
        external_id=row.external_id,
        included=row.included,
        horizon_days=row.horizon_days,
        sync_state=SyncStateRecord(
            last_success_at=row.last_success_at,
            last_attempt_at=row.last_attempt_at,
            last_error=row.last_error,
            cursor=row.cursor,
            events_read=row.events_read,
            anchors_current=row.anchors_current,
            # Copied out of the row rather than aliased: a mapped JSONB value is the mapper's
            # own mutable object, and handing it out would let a caller change the row.
            rejections=_from_rows(row.rejections),
        ),
    )
