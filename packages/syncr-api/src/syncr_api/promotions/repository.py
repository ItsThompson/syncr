"""Persistence for declined promotions. Tenant-scoped.

Two methods: record one decline, and read which patterns are still silenced. Both are built from the
scoped base, so the tenant predicate is applied by the base rather than remembered per method.

:meth:`PromotionDeclineRepository.silenced_at` reads only the rows whose suppression has not
expired, and it answers a set of identifiers rather than records. The caller compares it against the
candidates one detection pass found, so what it needs is membership; handing back rows would make
every caller decide again which of them are still in force.

Expired rows are NOT deleted. A decline is what the reader answered, and the answer outliving its
suppression is the record of it: `syncr_learning`'s corpus does not read this table, but a later
question about whether a promotion was ever offered and refused is answerable from it, and a reaper
would be a second rule about a table with one write.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.promotions.models import PromotionDecline
from syncr_api.promotions.records import PromotionDeclineRecord

if TYPE_CHECKING:
    from datetime import datetime

# The columns the one-decline-per-candidate index covers, as the upsert names them.
_IDENTITY = (TENANT_ID_COLUMN, "promotion_id")


class PromotionDeclineRepository(TenantScopedRepository):
    """One tenant's declined promotions: written per candidate, read as the set that is silenced."""

    async def decline(
        self, promotion_id: str, *, at: datetime, until: datetime
    ) -> PromotionDeclineRecord:
        """Record that this candidate was declined, replacing whatever an earlier decline said.

        Returned from the statement that wrote it rather than read back: the row's identity is the
        candidate and its primary key is not, so a second decline keeps the row and changes both
        instants.
        """
        written = await self._session.scalars(
            insert(PromotionDecline)
            .values(
                [
                    {
                        TENANT_ID_COLUMN: self.tenant_id,
                        "promotion_id": promotion_id,
                        "declined_at": at,
                        "suppressed_until": until,
                    }
                ]
            )
            .on_conflict_do_update(
                index_elements=list(_IDENTITY),
                set_={"declined_at": at, "suppressed_until": until},
            )
            .returning(PromotionDecline)
        )
        return _as_record(written.one())

    async def silenced_at(self, moment: datetime) -> frozenset[str]:
        """The identifiers of every candidate whose suppression still covers ``moment``.

        Half-open at the far end, as every interval in this product is: a suppression that ends
        exactly now is over, so the pattern is raised again in the session opened at that instant.
        """
        found = await self._session.scalars(
            self.scoped_select(PromotionDecline).where(PromotionDecline.suppressed_until > moment)
        )
        return frozenset(row.promotion_id for row in found)


def _as_record(row: PromotionDecline) -> PromotionDeclineRecord:
    return PromotionDeclineRecord(
        tenant_id=row.tenant_id,
        promotion_id=row.promotion_id,
        declined_at=row.declined_at,
        suppressed_until=row.suppressed_until,
    )
