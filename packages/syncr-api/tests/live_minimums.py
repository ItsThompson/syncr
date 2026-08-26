"""The least a plan can exist from: one declaration shared by every suite that drives a runner.

The suites that drive a real runner against a live tenant each kept a private copy of this
declaration, and the copies had drifted into three shapes of answer while seeding the same
rows. One helper lives here instead, and it answers every identifier a caller may need rather
than whatever shape that suite happened to want: the Area's identifier above all, because a
floor breach or a budget figure is asserted against it.

Rows beyond the minimum are how the suites differ -- one task the solver can place, or one
routine whose frame projects -- so those are declared as content callables the caller passes
in, not as boolean modes on this module. A suite states what its week holds at its own call
site; a sixth private copy of the whole declaration is what
:mod:`tests.test_the_one_live_minimum` exists to fail on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from syncr_api.areas.repository import AreaRepository
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.repository import DayTypeRepository, WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_domain.tasks import Priority
from syncr_domain.templates import WeekPattern
from syncr_domain.weeks import Weekday

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from syncr_domain.identifiers import TenantId

LONDON = "Europe/London"

# Monday of 2026-W07, mid-morning in London, so a fortnight's horizon covers W07 and W08.
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

# The Area every declaration creates, and the floor it declares. Named because suites make a week
# impossible by leaving less capacity than this floor, and the arithmetic has to be readable from
# the test rather than from the fixture.
AREA_NAME = "Career"
AREA_FLOOR_HOURS = Decimal(3)


@dataclass(frozen=True, slots=True)
class TenantMinimum:
    """What one declaration created, by identifier."""

    area_id: UUID
    day_type_id: UUID


async def declare_the_minimum(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    home_zone: str = LONDON,
    content: Callable[[AsyncSession, TenantId, UUID], Awaitable[None]] | None = None,
) -> TenantMinimum:
    """Areas, a day shape, a weight set, and a home zone: the least a plan can exist from.

    Deliberately less than a declared week. What the maintainers decide is whether a week HAS a
    plan and whether one CAN exist, and a fuller week would make every driver suite a second
    test of the assembler's resolutions. ``content`` adds the rows a suite's week needs inside
    the same transaction; without it the week solves to an empty document.
    """
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone=home_zone,
        )
        area = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name=AREA_NAME,
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=AREA_FLOOR_HOURS,
            created_at=NOW,
        )
        day_type = await DayTypeRepository(session, tenant_id).create(
            name="Weekday", created_at=NOW
        )
        await WeekPatternRepository(session, tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )
        if content is not None:
            await content(session, tenant_id, area.id)
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        return TenantMinimum(area_id=area.id, day_type_id=day_type.id)


async def a_placeable_task(session: AsyncSession, tenant_id: TenantId, area_id: UUID) -> None:
    """One task in the Area the solver can place.

    The task is what makes an authority path reachable: a week with an Area and no content
    solves to an empty document, which classifies as nothing and writes nothing, so a suite
    without it would assert about a solve that adopted no plan.
    """
    await TaskRepository(session, tenant_id).create(
        area_id=area_id,
        project_id=None,
        title="Interview preparation",
        estimate_minutes=120,
        deadline=None,
        priority=Priority.NORMAL,
        min_chunk_minutes=30,
        splittable=True,
        created_at=NOW,
    )


async def a_routine_frame(session: AsyncSession, tenant_id: TenantId, area_id: UUID) -> None:
    """One routine, so a materialized week holds blocks at all.

    Its Sunday-night occurrence is the span that crosses the ISO week boundary in real life,
    which is what a projection needs to meet.
    """
    await RoutineRepository(session, tenant_id).create(
        title="Sleep",
        target_time=time(23, 0),
        duration_minutes=8 * 60,
        min_duration_minutes=6 * 60,
        flex_band_minutes=60,
        created_at=NOW,
    )
