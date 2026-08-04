"""The immutable views of a day type, a shape, and one of its entries.

A repository hands back one of these rather than a mapped instance, so a service cannot trigger
a load it did not ask for and nothing downstream can change a row by assigning to it.

An entry's span is the domain's :class:`~syncr_domain.templates.EntrySpan` rather than three
loose fields, so a record read back from the database is subject to the same grid rule a
declaration was. A row that somehow held an off-grid span fails where it is read instead of
materializing a block the solver would refuse to place.

``TemplateRecord`` carries its entries. A tenant declares one shape per day type and a week has
seven weekdays, so the whole set is a handful of rows and reading them together means the list
and the single read are one code path rather than two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_domain.identifiers import (
        AreaId,
        DayTypeId,
        TemplateEntryId,
        TemplateId,
        TenantId,
    )
    from syncr_domain.templates import BindingTarget, EntrySpan, TemplateEntryKind


@dataclass(frozen=True, slots=True)
class DayTypeRecord:
    """One kind of day, as persistence knows it."""

    id: DayTypeId
    tenant_id: TenantId
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TemplateEntryRecord:
    """One part of a day shape.

    ``binding_target`` and ``binding_ref`` are set together or not at all, and which of the two
    states holds is decided by ``kind``. Nothing here re-checks that: the declaration shapes
    make an inconsistent entry unrepresentable and the table's check constraint holds the same
    pairing, so a record is a reading of a row that already satisfied it.
    """

    id: TemplateEntryId
    tenant_id: TenantId
    template_id: TemplateId
    kind: TemplateEntryKind
    span: EntrySpan
    area_id: AreaId | None
    binding_target: BindingTarget | None
    binding_ref: UUID | None


@dataclass(frozen=True, slots=True)
class TemplateRecord:
    """One day shape and its parts, in the order the day runs."""

    id: TemplateId
    tenant_id: TenantId
    day_type_id: DayTypeId
    name: str
    created_at: datetime
    entries: tuple[TemplateEntryRecord, ...]
