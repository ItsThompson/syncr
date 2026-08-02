"""Persistence for the settings row and the travel overrides. Tenant-scoped, both.

Every statement is built from the scoped base, so the tenant predicate is applied by the
base rather than remembered per method, and a repository cannot be constructed without a
tenant to scope to.

Two things here are load-bearing beyond ordinary reads and writes.

``read`` returns the DECLARED DEFAULTS when the tenant has no row, and writes nothing. A
tenant who has never opened Settings must be able to read them, and creating a row on a
GET would put a write on a read path for no gain: the values would be identical.

``lock`` is the tenant's serialization point for declaring a travel override. Overlap is
checked in the domain against the rows already stored, so two declarations racing would
both pass the check and both insert. Creating the row if it is absent and taking
``FOR UPDATE`` on it makes the check-then-insert atomic per tenant, without a second
implementation of the overlap rule in SQL.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.user_settings.config import (
    DAY_END_DEFAULT,
    DAY_START_DEFAULT,
    HOME_ZONE_DEFAULT,
    REVIEW_CADENCE_DEFAULT,
    VISIBLE_HOURS_DEFAULT,
)
from syncr_api.user_settings.models import Settings, TravelOverrideRow
from syncr_api.user_settings.records import SettingsRecord, TravelOverrideRecord

if TYPE_CHECKING:
    from datetime import date, datetime, time

    from syncr_api.user_settings.config import ReviewCadence
    from syncr_api.user_settings.records import TravelOverrideId


class SettingsRepository(TenantScopedRepository):
    """Reads, creates, and updates the one settings row a tenant has."""

    async def read(self) -> SettingsRecord:
        """This tenant's settings, or the declared defaults when no row exists."""
        found = await self._session.scalar(self.scoped_select(Settings))
        return _as_settings_record(found) if found is not None else self.defaults()

    def defaults(self) -> SettingsRecord:
        """What a tenant who has never saved settings reads."""
        return SettingsRecord(
            tenant_id=self.tenant_id,
            visible_hours=VISIBLE_HOURS_DEFAULT,
            day_start=DAY_START_DEFAULT,
            day_end=DAY_END_DEFAULT,
            review_cadence=REVIEW_CADENCE_DEFAULT,
            home_zone=HOME_ZONE_DEFAULT,
        )

    async def lock(self, *, created_at: datetime) -> SettingsRecord:
        """Create the row if it is absent, then hold it until the transaction ends.

        The returned record is the row's committed state, so a caller that merges a
        partial update onto it is merging onto values nobody else can change underneath.
        """
        await self._session.execute(
            insert(Settings)
            .values(tenant_id=self.tenant_id, created_at=created_at)
            .on_conflict_do_nothing(index_elements=[Settings.tenant_id])
        )
        locked = await self._session.scalar(self.scoped_select(Settings).with_for_update())
        if locked is None:  # pragma: no cover - the insert above guarantees the row
            message = f"the settings row for tenant {self.tenant_id} vanished after an upsert"
            raise RuntimeError(message)
        return _as_settings_record(locked)

    async def write(
        self,
        *,
        visible_hours: int,
        day_start: time,
        day_end: time,
        review_cadence: ReviewCadence,
        home_zone: str,
    ) -> SettingsRecord:
        """Replace every settings value. The caller has already merged its partial update.

        Whole-record rather than field-by-field, because the boundary validates the
        settings as a set: ``day_start`` and ``day_end`` have to be checked against each
        other, so the caller holds the merged values regardless.
        """
        await self._session.execute(
            self.scoped_update(Settings).values(
                visible_hours=visible_hours,
                day_start=day_start,
                day_end=day_end,
                review_cadence=review_cadence,
                home_zone=home_zone,
            )
        )
        return SettingsRecord(
            tenant_id=self.tenant_id,
            visible_hours=visible_hours,
            day_start=day_start,
            day_end=day_end,
            review_cadence=review_cadence,
            home_zone=home_zone,
        )


class TravelOverrideRepository(TenantScopedRepository):
    """Lists, creates, reads, and removes this tenant's travel overrides."""

    async def list_all(self) -> tuple[TravelOverrideRecord, ...]:
        """Every override this tenant has declared, in date order."""
        found = await self._session.scalars(
            self.scoped_select(TravelOverrideRow).order_by(
                TravelOverrideRow.start_date, TravelOverrideRow.end_date
            )
        )
        return tuple(_as_override_record(row) for row in found)

    async def find(self, override_id: TravelOverrideId) -> TravelOverrideRecord | None:
        """One override of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden,
        which is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(
            self.scoped_select(TravelOverrideRow).where(TravelOverrideRow.id == override_id)
        )
        return _as_override_record(found) if found is not None else None

    async def create(
        self, *, start_date: date, end_date: date, zone: str, created_at: datetime
    ) -> TravelOverrideRecord:
        """Persist one override. The caller has already rejected an overlap."""
        row = TravelOverrideRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            start_date=start_date,
            end_date=end_date,
            zone=zone,
            created_at=created_at,
        )
        self._session.add(row)
        # Flushed here so a constraint violation surfaces as this call's failure rather
        # than at commit, after the caller has reported success.
        await self._session.flush()
        return _as_override_record(row)

    async def remove(self, override_id: TravelOverrideId) -> None:
        """Delete one override of this tenant's."""
        await self._session.execute(
            self.scoped_delete(TravelOverrideRow).where(TravelOverrideRow.id == override_id)
        )


def _as_settings_record(row: Settings) -> SettingsRecord:
    return SettingsRecord(
        tenant_id=row.tenant_id,
        visible_hours=row.visible_hours,
        day_start=row.day_start,
        day_end=row.day_end,
        review_cadence=row.review_cadence,
        home_zone=row.home_zone,
    )


def _as_override_record(row: TravelOverrideRow) -> TravelOverrideRecord:
    return TravelOverrideRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        start_date=row.start_date,
        end_date=row.end_date,
        zone=row.zone,
    )
