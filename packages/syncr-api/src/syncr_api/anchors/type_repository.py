"""Persistence for ``anchor_types``. Tenant-scoped, and split from the anchor repository.

The two tables are read at different times by different callers. A sync pass reads every type
once and then writes many anchors; a rules screen reads and writes types and touches no anchor
at all. Keeping them apart is the same split plan storage makes between its plan of record, its
pending slot, and its version counter.

:meth:`AnchorTypeRepository.lock_all` is the serialization point for rule order. A create
appends at the end and a reorder rewrites every position, both derived from the whole set, so
two of either racing would otherwise read the same order and write conflicting positions.

``rule_order`` carries no unique constraint. A reorder rewrites positions row by row, and a
unique constraint would reject the intermediate states of any permutation that is not a
rotation. What makes evaluation order total instead is the read: position, then age, then
identifier, so first-match is deterministic even while a reorder is half-applied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from syncr_api.anchors.models import AnchorType
from syncr_api.anchors.records import AnchorTypeRecord, AnchorTypeSpecification
from syncr_api.core.repository import TenantScopedRepository
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy import Select

    from syncr_api.anchors.config import PostScope
    from syncr_api.anchors.records import AnchorTypeId
    from syncr_domain.identifiers import AreaId

_log = get_logger("syncr.anchors")


class AnchorTypeRepository(TenantScopedRepository):
    """Lists, reads, creates, updates, reorders, and removes one tenant's anchor types."""

    async def list_all(self) -> tuple[AnchorTypeRecord, ...]:
        """Every type this tenant declares, in evaluation order."""
        found = await self._session.scalars(self._ordered())
        return tuple(_as_record(row) for row in found)

    async def lock_all(self) -> tuple[AnchorTypeRecord, ...]:
        """:meth:`list_all`, held until the transaction ends.

        The returned records are the rows' committed state, so a caller appending at the end of
        the order or rewriting the whole order derives it from a set nobody else can change
        underneath.
        """
        found = await self._session.scalars(self._ordered().with_for_update())
        return tuple(_as_record(row) for row in found)

    async def find(self, anchor_type_id: AnchorTypeId) -> AnchorTypeRecord | None:
        """One type of this tenant's, or ``None``."""
        found = await self._session.scalar(
            self.scoped_select(AnchorType).where(AnchorType.id == anchor_type_id)
        )
        return _as_record(found) if found is not None else None

    async def create(
        self, *, rule_order: int, specification: AnchorTypeSpecification, created_at: datetime
    ) -> AnchorTypeRecord:
        """Persist one type. The caller has already validated its geometry and its references."""
        row = AnchorType(
            id=uuid4(),
            tenant_id=self.tenant_id,
            rule_order=rule_order,
            created_at=created_at,
            **_as_columns(specification),
        )
        self._session.add(row)
        # Flushed here so a duplicate name or a violated boundary constraint surfaces as this
        # call's failure rather than at commit, after the caller has reported success.
        await self._session.flush()
        return _as_record(row)

    async def write(
        self, anchor_type_id: AnchorTypeId, specification: AnchorTypeSpecification
    ) -> None:
        """Replace one type's whole specification. A ``PATCH`` was merged onto it first."""
        await self._session.execute(
            self.scoped_update(AnchorType)
            .where(AnchorType.id == anchor_type_id)
            .values(**_as_columns(specification))
        )
        await self._session.flush()

    async def set_rule_order(self, anchor_type_id: AnchorTypeId, *, rule_order: int) -> None:
        """Move one type to a position. The caller rewrites every position in one pass."""
        await self._session.execute(
            self.scoped_update(AnchorType)
            .where(AnchorType.id == anchor_type_id)
            .values(rule_order=rule_order)
        )

    async def remove(self, anchor_type_id: AnchorTypeId) -> None:
        """Delete one type of this tenant's. Its anchors were released first."""
        await self._session.execute(
            self.scoped_delete(AnchorType).where(AnchorType.id == anchor_type_id)
        )

    def _ordered(self) -> Select[tuple[AnchorType]]:
        """Evaluation order, made total: position, then age, then identifier."""
        return self.scoped_select(AnchorType).order_by(
            AnchorType.rule_order, AnchorType.created_at, AnchorType.id
        )


def _as_columns(specification: AnchorTypeSpecification) -> dict[str, object]:
    """One specification as the columns that hold it.

    Written out rather than derived from the dataclass fields, so a field added to the
    specification is a deliberate edit here rather than a silent attempt to write a column that
    does not exist.
    """
    return {
        "name": specification.name,
        "match_title_contains": specification.match_title_contains,
        "match_source_id": specification.match_source_id,
        "prep_lead_minutes": specification.prep_lead_minutes,
        "prep_duration_minutes": specification.prep_duration_minutes,
        "prep_area_id": specification.prep_area_id,
        "transit_lead_minutes": specification.transit_lead_minutes,
        "transit_duration_minutes": specification.transit_duration_minutes,
        "return_transit_minutes": specification.return_transit_minutes,
        "transit_area_id": specification.transit_area_id,
        "post_buffer_minutes": specification.post_buffer_minutes,
        "post_scope": specification.post_scope,
        "forbidden_area_ids": [str(area_id) for area_id in specification.forbidden_area_ids],
    }


def _as_record(row: AnchorType) -> AnchorTypeRecord:
    return AnchorTypeRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        rule_order=row.rule_order,
        specification=AnchorTypeSpecification(
            name=row.name,
            match_title_contains=row.match_title_contains,
            match_source_id=row.match_source_id,
            prep_lead_minutes=row.prep_lead_minutes,
            prep_duration_minutes=row.prep_duration_minutes,
            prep_area_id=row.prep_area_id,
            transit_lead_minutes=row.transit_lead_minutes,
            transit_duration_minutes=row.transit_duration_minutes,
            return_transit_minutes=row.return_transit_minutes,
            transit_area_id=row.transit_area_id,
            post_buffer_minutes=row.post_buffer_minutes,
            post_scope=cast("PostScope", row.post_scope),
            forbidden_area_ids=_as_area_ids(row.forbidden_area_ids),
        ),
    )


def _as_area_ids(stored: Sequence[str] | None) -> tuple[AreaId, ...]:
    """The stored JSONB array back as identifiers.

    A member that is not a UUID is dropped rather than raising. The column is JSONB and the check
    constraint bounds its shape rather than its members, so refusing to READ a tenant's anchor
    types because one stored member is malformed would be the wrong trade: the rules still
    evaluate and the type is still editable.

    The drop is LOGGED, because its consequence is otherwise undiagnosable. A dropped member can
    leave a stored ``scope=areas`` type whose list reads empty, and a later ``PATCH`` on an
    unrelated field then answers 422 on ``forbiddenAreaIds``, a field the caller never sent.
    """
    resolved: list[AreaId] = []
    dropped = 0
    for member in stored or ():
        try:
            resolved.append(UUID(member))
        except (AttributeError, TypeError, ValueError):
            dropped += 1
    if dropped:
        _log.warning("anchors.type.forbidden_area_dropped", dropped=dropped, kept=len(resolved))
    return tuple(resolved)
