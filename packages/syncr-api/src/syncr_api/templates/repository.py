"""Persistence for day types, shapes, entries, and the week pattern. Tenant-scoped, all four.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant to
scope to.

Two reads are worth a word.

:meth:`TemplateRepository.list_all` reads the shapes and their entries in two statements and
assembles them, rather than reading counts for a list and entries for a member. A tenant
declares one shape per day type and a week has seven weekdays, so the whole set is a handful of
rows: one code path that always returns whole shapes beats two that can disagree.

:meth:`WeekPatternRepository.read` returns the domain's :class:`WeekPattern`, which refuses an
incomplete mapping. Zero rows is "not declared yet" and is reported as ``None``; a partial set
of rows is a corruption rather than a state, because the only writer replaces all seven inside
one transaction, so it fails where it is read instead of materializing five days out of seven.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.templates.models import DayTypeRow, TemplateEntryRow, TemplateRow, WeekPatternRow
from syncr_api.templates.records import DayTypeRecord, TemplateEntryRecord, TemplateRecord
from syncr_domain.templates import EntrySpan, WeekPattern

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syncr_api.templates.declarations import EntryContent
    from syncr_domain.identifiers import DayTypeId, TemplateEntryId, TemplateId


class DayTypeRepository(TenantScopedRepository):
    """Lists, reads, and creates this tenant's day types."""

    async def list_all(self) -> tuple[DayTypeRecord, ...]:
        """Every day type this tenant has declared, in the order they were declared."""
        found = await self._session.scalars(
            self.scoped_select(DayTypeRow).order_by(DayTypeRow.created_at, DayTypeRow.id)
        )
        return tuple(_as_day_type(row) for row in found)

    async def create(self, *, name: str, created_at: datetime) -> DayTypeRecord:
        """Persist one day type. The caller has already checked its name is free."""
        row = DayTypeRow(id=uuid4(), tenant_id=self.tenant_id, name=name, created_at=created_at)
        self._session.add(row)
        # Flushed here so a constraint violation surfaces as this call's failure rather than at
        # commit, after the caller has reported success.
        await self._session.flush()
        return _as_day_type(row)


class TemplateRepository(TenantScopedRepository):
    """Reads, creates, changes, and removes this tenant's day shapes and their entries."""

    async def list_all(self) -> tuple[TemplateRecord, ...]:
        """Every shape with its entries, oldest shape first."""
        shapes = await self._session.scalars(
            self.scoped_select(TemplateRow).order_by(TemplateRow.created_at, TemplateRow.id)
        )
        entries = await self._entries()
        return tuple(_as_template(row, entries.get(row.id, ())) for row in shapes)

    async def find(self, template_id: TemplateId) -> TemplateRecord | None:
        """One shape of this tenant's with its entries, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden, which
        is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(
            self.scoped_select(TemplateRow).where(TemplateRow.id == template_id)
        )
        if found is None:
            return None
        entries = await self._entries(template_id)
        return _as_template(found, entries.get(template_id, ()))

    async def find_by_day_type(self, day_type_id: DayTypeId) -> TemplateRecord | None:
        """The shape declared for this day type, or ``None``. At most one exists."""
        found = await self._session.scalar(
            self.scoped_select(TemplateRow).where(TemplateRow.day_type_id == day_type_id)
        )
        if found is None:
            return None
        entries = await self._entries(found.id)
        return _as_template(found, entries.get(found.id, ()))

    async def create(
        self, *, day_type_id: DayTypeId, name: str, created_at: datetime
    ) -> TemplateRecord:
        """Persist one shape, with no entries yet."""
        row = TemplateRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            day_type_id=day_type_id,
            name=name,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _as_template(row, ())

    async def write(self, template_id: TemplateId, *, name: str) -> None:
        """Replace the one editable value on a shape.

        The day type is absent: a shape is the shape OF its day type, and there is exactly one
        per day type, so there is nowhere for it to move to.
        """
        await self._session.execute(
            self.scoped_update(TemplateRow).where(TemplateRow.id == template_id).values(name=name)
        )

    async def remove(self, template_id: TemplateId) -> None:
        """Delete one shape. Its entries go with it, through the foreign key's cascade."""
        await self._session.execute(
            self.scoped_delete(TemplateRow).where(TemplateRow.id == template_id)
        )

    async def create_entry(
        self, *, template_id: TemplateId, span: EntrySpan, content: EntryContent
    ) -> TemplateEntryRecord:
        """Persist one entry of a shape.

        ``content`` is produced by one of the two declaration shapes, so the four values below
        are already a legal combination and nothing here decides which combinations are.
        """
        row = TemplateEntryRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            template_id=template_id,
            kind=content.kind,
            target_time=span.target_time,
            duration_minutes=span.duration_minutes,
            flex_band_minutes=span.flex_band_minutes,
            area_id=content.area_id,
            binding_target=content.binding_target,
            binding_ref=content.binding_ref,
        )
        self._session.add(row)
        await self._session.flush()
        return _as_entry(row)

    async def write_entry(self, entry_id: TemplateEntryId, *, span: EntrySpan) -> None:
        """Replace one entry's span. Its content is declared once and is not editable."""
        await self._session.execute(
            self.scoped_update(TemplateEntryRow)
            .where(TemplateEntryRow.id == entry_id)
            .values(
                target_time=span.target_time,
                duration_minutes=span.duration_minutes,
                flex_band_minutes=span.flex_band_minutes,
            )
        )

    async def remove_entry(self, entry_id: TemplateEntryId) -> None:
        """Delete one entry of a shape."""
        await self._session.execute(
            self.scoped_delete(TemplateEntryRow).where(TemplateEntryRow.id == entry_id)
        )

    async def _entries(
        self, template_id: TemplateId | None = None
    ) -> dict[TemplateId, tuple[TemplateEntryRecord, ...]]:
        """This tenant's entries by shape, each shape's in the order the day runs.

        Two entries at one target time are ordered by identifier. That is arbitrary but stable,
        and nothing reads a declaration order: the target time IS the order a day shape has.
        """
        statement = self.scoped_select(TemplateEntryRow).order_by(
            TemplateEntryRow.target_time, TemplateEntryRow.id
        )
        if template_id is not None:
            statement = statement.where(TemplateEntryRow.template_id == template_id)
        found = await self._session.scalars(statement)
        by_shape: dict[TemplateId, tuple[TemplateEntryRecord, ...]] = {}
        for row in found:
            by_shape[row.template_id] = (*by_shape.get(row.template_id, ()), _as_entry(row))
        return by_shape


class WeekPatternRepository(TenantScopedRepository):
    """Reads and replaces this tenant's weekday-to-day-type mapping."""

    async def read(self) -> WeekPattern | None:
        """The pattern, or ``None`` when this tenant has not declared one."""
        found = tuple(await self._session.scalars(self.scoped_select(WeekPatternRow)))
        if not found:
            return None
        return WeekPattern({row.weekday: row.day_type_id for row in found})

    async def replace(self, pattern: WeekPattern) -> None:
        """Write all seven rows, replacing whatever was mapped before.

        A delete and seven inserts in the caller's transaction, rather than seven upserts: the
        pattern is replaced whole, so there is no per-weekday merge to express, and a mapping
        that is never partway through being applied is one no reader can catch mid-write.
        """
        await self._session.execute(self.scoped_delete(WeekPatternRow))
        self._session.add_all(
            [
                WeekPatternRow(tenant_id=self.tenant_id, weekday=weekday, day_type_id=day_type_id)
                for weekday, day_type_id in pattern.mapping.items()
            ]
        )
        await self._session.flush()


def _as_day_type(row: DayTypeRow) -> DayTypeRecord:
    return DayTypeRecord(
        id=row.id, tenant_id=row.tenant_id, name=row.name, created_at=row.created_at
    )


def _as_template(row: TemplateRow, entries: Sequence[TemplateEntryRecord]) -> TemplateRecord:
    return TemplateRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        day_type_id=row.day_type_id,
        name=row.name,
        created_at=row.created_at,
        entries=tuple(entries),
    )


def _as_entry(row: TemplateEntryRow) -> TemplateEntryRecord:
    return TemplateEntryRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        template_id=row.template_id,
        kind=row.kind,
        span=EntrySpan(
            target_time=row.target_time,
            duration_minutes=row.duration_minutes,
            flex_band_minutes=row.flex_band_minutes,
        ),
        area_id=row.area_id,
        binding_target=row.binding_target,
        binding_ref=row.binding_ref,
    )
