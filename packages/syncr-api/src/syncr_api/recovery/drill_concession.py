"""The one thing an approved tradeoff persists, and the read that keeps a repeat from rewriting it.

**Written through the repository an approval writes it through.** Requesting a tradeoff persists
nothing by design: the candidate rides on the operation and only an approval makes it real. Reaching
one through the request path needs a week short enough that syncr offers a concession for it, which
is a fixture with a capacity budget rather than a seeder, so what is written here is the write
itself, with the solve's own operation named as its cause.

Its own module because it is the one seam the rest of the week's history does not share: every other
step writes something the plan holds, and this one writes an agreement about the plan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_domain.plan import AdjustmentKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_api.recovery.drill_week import DrillWeek
    from syncr_domain.identifiers import AreaId, OperationId, TenantId

# How much of the drill's Area floor the concession excuses. A figure rather than a measurement: the
# row exists so a restore has a concession to bring back, and what a real one would excuse is
# decided by the shortfall that offered it.
FLOOR_BREACH_MINUTES: Final = 60


async def concede_a_floor_breach(
    session: AsyncSession,
    tenant_id: TenantId,
    week: DrillWeek,
    *,
    area_id: AreaId,
    operation_id: OperationId,
) -> WeekAdjustmentRecord:
    """Record the concession an approval records: this Area's floor, breached by agreement.

    An upsert on the week, the kind and the target, so a first run cannot accumulate rows. What
    keeps a REPEAT run from writing is the read beside this one: the upsert converges the row's
    identity and not its contents, because `created_by_operation_id` is whichever solve the run had
    in hand.
    """
    return await WeekAdjustmentRepository(session, tenant_id).upsert(
        iso_week=week.iso_week,
        kind=AdjustmentKind.BREACH_FLOOR.value,
        target_id=area_id,
        created_at=week.lived_at,
        created_by_operation_id=operation_id,
        delta_minutes=FLOOR_BREACH_MINUTES,
    )


async def already_conceded(
    session: AsyncSession, tenant_id: TenantId, week: DrillWeek, *, area_id: AreaId
) -> bool:
    """Whether the week already holds this concession, over the kind and target that key it.

    The read every sibling step has, and it is what makes a repeat run write no byte rather than the
    same row again: an upsert would rewrite the cause with whichever solve the second run resolved,
    and the drill's own verdict compares a table's contents rather than its count.
    """
    held = await WeekAdjustmentRepository(session, tenant_id).for_week(week.iso_week)
    return any(
        one.kind == AdjustmentKind.BREACH_FLOOR.value and one.target_id == area_id for one in held
    )
