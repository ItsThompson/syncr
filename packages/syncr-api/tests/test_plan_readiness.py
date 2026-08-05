"""The minimum inputs a week needs, and what a tenant missing them is told.

Driven over the two repositories' own reads rather than through a whole assembly, because the
question is one bit per declaration and the two callers -- the horizon maintainer and the Week
screen's empty state -- both want the same answer for the same reason.

The order of the missing list matters and is asserted: a user reading it is being told what to do
next, and a day shape has nowhere to charge its slots until an Area exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syncr_api.areas.repository import AreaRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.readiness import MinimumInputs, MissingInput, PlanReadiness
from syncr_api.templates.repository import DayTypeRepository, WeekPatternRepository
from syncr_domain.templates import WeekPattern
from syncr_domain.weeks import Weekday
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


async def declare_an_area(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> None:
    async with sessions() as session, session.begin():
        await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )


async def declare_a_day_shape(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    async with sessions() as session, session.begin():
        day_type = await DayTypeRepository(session, tenant_id).create(
            name="Weekday", created_at=NOW
        )
        await WeekPatternRepository(session, tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )


async def read(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> PlanReadiness:
    async with sessions() as session:
        return await MinimumInputs(
            AreaRepository(session, tenant_id), WeekPatternRepository(session, tenant_id)
        ).read()


async def test_a_tenant_who_has_declared_nothing_is_missing_both(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    readiness = await read(sessions, owner.tenant_id)

    assert readiness.missing == (MissingInput.AREAS, MissingInput.DAY_SHAPE)
    assert not readiness.is_ready


async def test_areas_alone_are_not_enough(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """A day shape is what materializes anything: without one the frame is the whole plan."""
    await declare_an_area(sessions, owner.tenant_id)

    readiness = await read(sessions, owner.tenant_id)

    assert readiness.missing == (MissingInput.DAY_SHAPE,)


async def test_a_day_shape_alone_is_not_enough(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """Every discretionary block is charged to an Area, so a plan with none charges nothing."""
    await declare_a_day_shape(sessions, owner.tenant_id)

    readiness = await read(sessions, owner.tenant_id)

    assert readiness.missing == (MissingInput.AREAS,)


async def test_both_declared_is_ready(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await declare_an_area(sessions, owner.tenant_id)
    await declare_a_day_shape(sessions, owner.tenant_id)

    readiness = await read(sessions, owner.tenant_id)

    assert readiness.is_ready
    assert readiness.missing == ()


async def test_another_tenants_declarations_do_not_make_this_one_ready(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """The read is scoped, and a fake could not show that."""
    other = await seed_owner(sessions)
    try:
        await declare_an_area(sessions, other.tenant_id)
        await declare_a_day_shape(sessions, other.tenant_id)

        assert not (await read(sessions, owner.tenant_id)).is_ready
    finally:
        await delete_tenant(sessions, other.tenant_id)


def test_the_statement_names_the_thing_the_user_has_to_create() -> None:
    """Not the column it is stored in: the empty state is read by a person, not an operator."""
    both = PlanReadiness((MissingInput.AREAS, MissingInput.DAY_SHAPE))

    assert both.statement() == "at least one Area and a day shape for each weekday"


def test_a_ready_week_states_nothing() -> None:
    assert PlanReadiness().statement() == ""


@pytest.mark.parametrize("missing", list(MissingInput), ids=[one.value for one in MissingInput])
def test_every_missing_input_has_a_wording(missing: MissingInput) -> None:
    """Bounded by the vocabulary: a third minimum input is unworded until it is named."""
    assert PlanReadiness((missing,)).statement()
