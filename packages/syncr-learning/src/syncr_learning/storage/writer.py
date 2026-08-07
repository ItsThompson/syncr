"""The one write this job performs: append a new weight-set version. No update, no delete.

Each run APPENDS rather than mutating the current row, so comparison and rollback are free and a
revert is a flag. The version is the tenant's own maximum plus one, taken inside the transaction
that inserts, so two runs landing together cannot read one number and write the same successor: the
table's composite primary key is what refuses the second, and the refusal is the guarantee rather
than the read.

**The new row is not active.** Activation is a user-facing act with a re-solve behind it, and it
belongs to the screen that offers it. A nightly job that activated its own output would move the
plan under the user overnight. **There is no ``ON CONFLICT`` clause, and its absence is the
append-only rule.** ``weight_sets`` has a composite primary key of tenant and version, so an upsert
would let a second run overwrite the version the first wrote. A collision is refused by the key and
the refusal is what the run reports as a failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sqlalchemy import column, func, insert, select, table
from sqlalchemy.dialects.postgresql import JSONB

from syncr_learning.storage import spelling

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from syncr_domain.identifiers import TenantId
    from syncr_learning.artifact import FittedWeightSet

FIRST_VERSION: Final = 1

# The three JSONB columns carry their TYPE, not only their name. A column built without one is sent
# to the driver as a raw parameter, and asyncpg cannot encode a dict: the insert fails at the driver
# rather than at the schema, which is a failure whose message names nothing about weight sets.
#
# Every name comes from `spelling`, not from a literal. `spelling`'s own docstring gives the reason:
# a literal inside a query cannot be crossed against anything, and twelve of these were literals.
_WEIGHT_SETS = table(
    spelling.WEIGHT_SETS,
    column(spelling.TENANT_ID),
    column(spelling.VERSION),
    column(spelling.ACTIVE),
    column(spelling.ORIGIN),
    column(spelling.DEADLINE_RISK),
    column(spelling.BUDGET_DEVIATION),
    column(spelling.TIME_OF_DAY_MISFIT),
    column(spelling.FRAGMENTATION),
    column(spelling.CHURN),
    column(spelling.CONTEXT_SWITCH),
    column(spelling.STALENESS),
    column(spelling.DURATION_MULTIPLIER, JSONB),
    column(spelling.TIME_OF_DAY_FITNESS, JSONB),
    column(spelling.SKIP_PROBABILITY, JSONB),
    column(spelling.CONTEXT_SWITCH_COST),
    column(spelling.CHURN_TOLERANCE),
    column(spelling.FITTED_AT),
    column(spelling.MATURITY, JSONB),
    column(spelling.CREATED_AT),
)


class PostgresParameterWriter:
    """One deployment's appended weight-set versions."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append_version(self, tenant_id: TenantId, fitted: FittedWeightSet) -> int:
        """Insert the next version for this tenant and answer with the number it took."""
        async with self._sessions.begin() as session:
            version = await self._next_version(session, tenant_id)
            await session.execute(
                insert(_WEIGHT_SETS).values(
                    {
                        spelling.TENANT_ID: tenant_id,
                        spelling.VERSION: version,
                        spelling.ACTIVE: False,
                        spelling.CREATED_AT: fitted.fitted_at,
                        **fitted.columns(),
                    }
                )
            )
            return version

    async def _next_version(self, session: AsyncSession, tenant_id: TenantId) -> int:
        highest = await session.scalar(
            select(func.max(_WEIGHT_SETS.c.version)).where(_WEIGHT_SETS.c.tenant_id == tenant_id)
        )
        return FIRST_VERSION if highest is None else int(highest) + 1
