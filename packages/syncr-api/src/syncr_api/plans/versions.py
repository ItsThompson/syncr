"""The week input version: one counter, and the guard every solve's write is made under.

This row is the single serialization point for anything that invalidates a running solve,
whether it changed the solve inputs or the live plan. That is why one guard suffices and
why there is no dirty flag: a mutation arriving mid-solve bumps this counter, the solve's
conditional write then fails, and exactly one follow-up is enqueued.

Two states need care, and both are normal rather than exceptional.

A week nobody has touched has NO row. The horizon maintainer solves such weeks, so the
first reference creates the row at version 1, in the reference's own transaction.

A missing row is a MISMATCH, not a match. ``SELECT ... FOR UPDATE`` on an absent row takes
no lock and has nothing to compare, so failing open would let two concurrent first solves
both commit. :meth:`WeekInputVersionRepository.holds_version` therefore reports a mismatch
in that case, and the follow-up solve finds the row this one created.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.config import FIRST_INPUT_VERSION
from syncr_api.plans.models import WeekInputVersion

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.weeks import IsoWeek


class WeekInputVersionRepository(TenantScopedRepository):
    """The per-week input counter for one tenant."""

    async def bump(self, iso_week: IsoWeek, *, at: datetime) -> int:
        """Raise the week's version, creating the row at 1, and return the new value.

        Called in the SAME transaction as the mutation that caused it. A mutation that
        committed without its bump would leave a running solve believing it had read
        current inputs.

        One statement, so two mutations landing together cannot read the same value and
        write the same successor: the second waits on the first's row lock and increments
        what it committed.
        """
        statement = (
            insert(WeekInputVersion)
            .values(
                {
                    TENANT_ID_COLUMN: self.tenant_id,
                    "iso_week": str(iso_week),
                    "version": FIRST_INPUT_VERSION,
                    "updated_at": at,
                }
            )
            .on_conflict_do_update(
                index_elements=[TENANT_ID_COLUMN, "iso_week"],
                set_={"version": WeekInputVersion.version + 1, "updated_at": at},
            )
            .returning(WeekInputVersion.version)
        )
        return (await self._session.scalars(statement)).one()

    async def current(self, iso_week: IsoWeek) -> int | None:
        """The week's version, or ``None`` when nothing has referenced the week yet."""
        return await self._session.scalar(
            self.scoped_select(WeekInputVersion)
            .where(WeekInputVersion.iso_week == str(iso_week))
            .with_only_columns(WeekInputVersion.version)
        )

    async def holds_version(self, iso_week: IsoWeek, version: int, *, at: datetime) -> bool:
        """Whether the week is still at ``version``, with the row locked until this commits.

        The lock is the point: reading the version, comparing it, and writing the revision
        must not interleave with another mutation's bump, so the row is taken ``FOR
        UPDATE`` and held for the rest of the caller's transaction.

        A missing row is created at version 1 here and reported as a mismatch, which is
        what stops two concurrent first solves from both committing.
        """
        found = await self._session.scalar(
            self.scoped_select(WeekInputVersion)
            .where(WeekInputVersion.iso_week == str(iso_week))
            .with_for_update()
        )
        if found is None:
            await self.bump(iso_week, at=at)
            return False
        return found.version == version
