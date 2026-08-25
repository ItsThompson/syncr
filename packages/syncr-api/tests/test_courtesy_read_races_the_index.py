"""A rule stated twice: the read that refuses a request, and the unique index behind it.

Two rules here are stated in both places on purpose. The read holds no lock, so two requests
can pass it together and the index is what refuses the second write. The two halves fail
differently, so they are evidenced differently.

**The behaviour half is driven over two real connections.** A conflicting row is committed
between the read and the write, and what the loser is answered has to be the refusal the read
would have raised rather than a fault. A seam in the repository announces the window and waits
inside it, so the interleaving is stated rather than hoped for.

**The guarantee half is read off the database.** Both indexes exist in the migrated schema over
the columns the tables declare; the refusal Postgres raises names one of them; and the plan it
produces for the shape read, captured as the repository sent it, is an index scan on the index
that guarantees the same rule.

No plan claim is made for the day-type name. That read lists a tenant's day types whole, so
nothing about it is an index lookup: the unique index over the name guarantees the write and
nothing else.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from syncr_api.areas.repository import AreaRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, Conflict
from syncr_api.core.principal import Principal
from syncr_api.core.races import answered_once, refused_index
from syncr_api.core.scopes import Scope
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.habits.repository import HabitRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.templates.bindings import TemplateBindings
from syncr_api.templates.config import (
    DAY_TYPES_PREFIX,
    ONE_DAY_TYPE_PER_NAME_INDEX,
    ONE_SHAPE_PER_DAY_TYPE_INDEX,
)
from syncr_api.templates.declarations import DayTypeDeclaration, TemplateDeclaration
from syncr_api.templates.invalidation import FutureWeeks
from syncr_api.templates.models import DayTypeRow, TemplateRow
from syncr_api.templates.repository import (
    DayTypeRepository,
    TemplateRepository,
    WeekPatternRepository,
)
from syncr_api.templates.rules import require_an_unshaped_day_type
from syncr_api.templates.service import DayTypeService, TemplateService
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions
from tests.control_models import recording, table_of
from tests.live_races import Window, signed_in, the_unique_index_over, wired_app
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    import httpx
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.templates.records import DayTypeRecord, TemplateRecord
    from syncr_domain.identifiers import DayTypeId, TenantId
    from tests.control_models import StatementRecorder

    type Duplicate = Callable[[AsyncSession, TenantId, DayTypeId], Awaitable[object]]

pytestmark = pytest.mark.integration

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
A_NAME = "Weekday"
A_SHAPE_NAME = "Weekday shape"

# Long enough that the racing connection's commit lands inside it, short enough that a window
# nobody closes fails the test rather than hanging the suite.
WINDOW_SECONDS = 5

# Enough rows that the planner prefers the unique index to reading the table whole. It decides
# that by cost, not by a row count: a sequential scan is cheaper until the table's page count
# makes it dearer than the index's fixed estimate, so the row count where it flips depends on how
# wide the rows are. On this fixture it flips between 200 and 250. A plan asserted below the flip
# would be asserting the planner's arithmetic rather than the index, so this sits well above it.
ROWS_THE_CHOICE_IS_REAL_AT = 1000


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


@pytest.fixture
def statements(engine: AsyncEngine) -> Iterator[StatementRecorder]:
    yield from recording(engine)


def a_principal(owner: UserRecord) -> Principal:
    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset(Scope))


class DayTypesReadInsideAWindow(DayTypeRepository):
    """The day-type list, answering only once the racing write has landed."""

    def __init__(self, session: AsyncSession, tenant_id: TenantId, *, window: Window) -> None:
        super().__init__(session, tenant_id)
        self._window = window

    async def list_all(self) -> tuple[DayTypeRecord, ...]:
        found = await super().list_all()
        await self._window.hold()
        return found


class ShapesReadInsideAWindow(TemplateRepository):
    """The one-shape read, answering only once the racing write has landed."""

    def __init__(self, session: AsyncSession, tenant_id: TenantId, *, window: Window) -> None:
        super().__init__(session, tenant_id)
        self._window = window

    async def find_by_day_type(self, day_type_id: DayTypeId) -> TemplateRecord | None:
        found = await super().find_by_day_type(day_type_id)
        await self._window.hold()
        return found


def a_day_type_service(
    session: AsyncSession, owner: UserRecord, *, day_types: DayTypeRepository | None = None
) -> DayTypeService:
    """The production service, with only the repository substitutable."""
    return DayTypeService(
        day_types=day_types or DayTypeRepository(session, owner.tenant_id),
        clock=lambda: NOW,
        savepoint=session.begin_nested,
    )


def a_template_service(
    session: AsyncSession, owner: UserRecord, *, templates: TemplateRepository | None = None
) -> TemplateService:
    """The production service, wired as a request wires it, with only the shapes substitutable."""
    return TemplateService(
        templates=templates or TemplateRepository(session, owner.tenant_id),
        day_types=DayTypeRepository(session, owner.tenant_id),
        areas=AreaRepository(session, owner.tenant_id),
        bindings=TemplateBindings(
            routines=RoutineRepository(session, owner.tenant_id),
            habits=HabitRepository(session, owner.tenant_id),
        ),
        weeks=FutureWeeks(
            patterns=WeekPatternRepository(session, owner.tenant_id),
            bump=BacklogWideBump(
                versions=TrackedWeekInputVersions(
                    WeekInputVersionRepository(session, owner.tenant_id), clock=lambda: NOW
                ),
                settings=SettingsRepository(session, owner.tenant_id),
            ),
            clock=lambda: NOW,
        ),
        clock=lambda: NOW,
        savepoint=session.begin_nested,
    )


def on_the_wire(error: Conflict) -> dict[str, Any]:
    """What a caller receives, minus the correlation id that differs per request."""
    return error.as_problem().model_dump(exclude={"instance"}, exclude_none=True)


async def a_day_type(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, name: str = A_NAME
) -> DayTypeRecord:
    async with sessions() as session, session.begin():
        return await DayTypeRepository(session, owner.tenant_id).create(name=name, created_at=NOW)


async def a_shape(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    day_type: DayTypeRecord,
    name: str = A_SHAPE_NAME,
) -> TemplateRecord:
    async with sessions() as session, session.begin():
        return await TemplateRepository(session, owner.tenant_id).create(
            day_type_id=day_type.id, name=name, created_at=NOW
        )


# --------------------------------------------------------------------------------
# The behaviour: what the loser of the race is answered
# --------------------------------------------------------------------------------


async def test_a_name_taken_inside_the_window_answers_the_reads_own_refusal(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    window = Window(hold_for=WINDOW_SECONDS)

    async def declare_inside_the_window() -> DayTypeRecord:
        async with sessions() as session, session.begin():
            service = a_day_type_service(
                session,
                owner,
                day_types=DayTypesReadInsideAWindow(session, owner.tenant_id, window=window),
            )
            return await service.create(a_principal(owner), DayTypeDeclaration(name=A_NAME))

    async def take_the_name() -> None:
        await window.open.wait()
        await a_day_type(sessions, owner)
        window.closed.set()

    raced = asyncio.create_task(declare_inside_the_window())
    winner = asyncio.create_task(take_the_name())
    await asyncio.wait_for(winner, timeout=WINDOW_SECONDS)
    with pytest.raises(Conflict) as refused:
        await asyncio.wait_for(raced, timeout=WINDOW_SECONDS)

    assert on_the_wire(refused.value) == await the_refusal_the_name_read_raises(sessions, owner)
    assert window.reads == 2, (
        "the refused write did not read again, so the words it answered with were copied from "
        "the read rather than raised by it"
    )
    async with sessions() as session:
        stored = await DayTypeRepository(session, owner.tenant_id).list_all()
    assert [row.name for row in stored] == [A_NAME]


async def test_a_shape_declared_inside_the_window_answers_the_reads_own_refusal(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    day_type = await a_day_type(sessions, owner)
    window = Window(hold_for=WINDOW_SECONDS)

    async def declare_inside_the_window() -> TemplateRecord:
        async with sessions() as session, session.begin():
            service = a_template_service(
                session,
                owner,
                templates=ShapesReadInsideAWindow(session, owner.tenant_id, window=window),
            )
            return await service.create(
                a_principal(owner),
                TemplateDeclaration(day_type_id=day_type.id, name="Another shape"),
            )

    async def take_the_day_type() -> None:
        await window.open.wait()
        await a_shape(sessions, owner, day_type)
        window.closed.set()

    raced = asyncio.create_task(declare_inside_the_window())
    winner = asyncio.create_task(take_the_day_type())
    await asyncio.wait_for(winner, timeout=WINDOW_SECONDS)
    with pytest.raises(Conflict) as refused:
        await asyncio.wait_for(raced, timeout=WINDOW_SECONDS)

    # This detail carries the winning shape's OWN name, which the losing request never held, so
    # only a refusal raised by reading again can produce it.
    assert on_the_wire(refused.value) == await the_refusal_the_shape_read_raises(
        sessions, owner, day_type
    )
    assert A_SHAPE_NAME in refused.value.detail
    assert window.reads == 2
    async with sessions() as session:
        stored = await TemplateRepository(session, owner.tenant_id).list_all()
    assert [row.name for row in stored] == [A_SHAPE_NAME]


async def the_refusal_the_name_read_raises(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> dict[str, Any]:
    """What an unraced request for a name that is already taken is answered."""
    async with sessions() as session, session.begin():
        service = a_day_type_service(session, owner)
        with pytest.raises(Conflict) as refused:
            await service.create(a_principal(owner), DayTypeDeclaration(name=A_NAME))
    return on_the_wire(refused.value)


async def the_refusal_the_shape_read_raises(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, day_type: DayTypeRecord
) -> dict[str, Any]:
    """What an unraced request for a day type that already has a shape is answered."""
    async with sessions() as session, session.begin():
        service = a_template_service(session, owner)
        with pytest.raises(Conflict) as refused:
            await service.create(
                a_principal(owner),
                TemplateDeclaration(day_type_id=day_type.id, name="Another shape"),
            )
    return on_the_wire(refused.value)


async def test_a_refusal_from_another_index_is_left_to_whoever_owns_it(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # One helper call answers for one rule. Answering for `IntegrityError` as a class would
    # answer for every rule at once and could not say which of them was broken.
    await a_day_type(sessions, owner)
    restated = False

    async def restate() -> None:
        nonlocal restated
        restated = True

    async with sessions() as session, session.begin():
        day_types = DayTypeRepository(session, owner.tenant_id)
        with pytest.raises(IntegrityError):
            await answered_once(
                savepoint=session.begin_nested,
                index=ONE_SHAPE_PER_DAY_TYPE_INDEX,
                write=lambda: day_types.create(name=A_NAME, created_at=NOW),
                refusal=restate,
            )

    assert restated is False


async def test_a_refused_write_whose_row_is_already_gone_is_still_a_conflict(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The interleaving with a third writer in it: the shape that refused this write is removed
    # before the read can see it, so there is no refusal to restate. Only the status is asserted.
    # What this state should say to the caller is a product question, and a test that pinned the
    # wording would answer it by accident.
    day_type = await a_day_type(sessions, owner)
    shape = await a_shape(sessions, owner, day_type)

    async with sessions() as session, session.begin():
        templates = TemplateRepository(session, owner.tenant_id)

        async def restate_after_the_shape_goes() -> None:
            async with sessions() as other, other.begin():
                await TemplateRepository(other, owner.tenant_id).remove(shape.id)
            require_an_unshaped_day_type(await templates.find_by_day_type(day_type.id))

        with pytest.raises(Conflict) as refused:
            await answered_once(
                savepoint=session.begin_nested,
                index=ONE_SHAPE_PER_DAY_TYPE_INDEX,
                write=lambda: templates.create(
                    day_type_id=day_type.id, name="Another shape", created_at=NOW
                ),
                refusal=restate_after_the_shape_goes,
            )

    # `HTTPStatus.CONFLICT` rather than `Conflict.status`: this test's whole point is that the
    # answer is not a 500, and reading the status off the class that raised it would pass however
    # that class was renumbered.
    assert refused.value.as_problem().status == HTTPStatus.CONFLICT


# --------------------------------------------------------------------------------
# The guarantee: the indexes, and what the database says about them
# --------------------------------------------------------------------------------


async def a_second_day_type_of_one_name(
    session: AsyncSession, tenant_id: TenantId, _day_type_id: DayTypeId
) -> object:
    return await DayTypeRepository(session, tenant_id).create(name=A_NAME, created_at=NOW)


async def a_second_shape_for_one_day_type(
    session: AsyncSession, tenant_id: TenantId, day_type_id: DayTypeId
) -> object:
    return await TemplateRepository(session, tenant_id).create(
        day_type_id=day_type_id, name="Another shape", created_at=NOW
    )


@pytest.mark.parametrize(
    ("index", "duplicate"),
    [
        (ONE_DAY_TYPE_PER_NAME_INDEX, a_second_day_type_of_one_name),
        (ONE_SHAPE_PER_DAY_TYPE_INDEX, a_second_shape_for_one_day_type),
    ],
)
async def test_the_database_blames_the_index_this_rule_leans_on_by_name(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    index: str,
    duplicate: Duplicate,
) -> None:
    # What the helper matches on. The driver reports the offended constraint on the error it
    # raises and SQLAlchemy wraps that error rather than copying its fields, so this is the
    # reading that has to keep working: a driver that stopped carrying the name would leave
    # every one of these races answered 500 again.
    day_type = await a_day_type(sessions, owner)
    await a_shape(sessions, owner, day_type)

    async with sessions() as session, session.begin():
        with pytest.raises(IntegrityError) as refused:
            async with session.begin_nested():
                await duplicate(session, owner.tenant_id, day_type.id)

    assert refused_index(refused.value) == index


async def test_both_rules_indexes_are_unique_in_the_migrated_schema_over_the_columns_declared(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Crossed rather than restated: the columns come from the tables' own declarations and the
    # names the write path uses have to be among them, so a rename that reaches one surface and
    # not the other is red here.
    declared = {
        index.name: tuple(column.name for column in index.columns)
        for table in (DayTypeRow, TemplateRow)
        for index in table_of(table).indexes
        if index.unique
    }
    assert {ONE_DAY_TYPE_PER_NAME_INDEX, ONE_SHAPE_PER_DAY_TYPE_INDEX} <= set(declared)

    async with sessions() as session:
        migrated = {
            str(row.index_name): (bool(row.is_unique), tuple(row.columns))
            for row in await session.execute(
                text(
                    "SELECT i.relname AS index_name, ix.indisunique AS is_unique, "
                    "  array_agg(a.attname ORDER BY k.ord) AS columns "
                    "FROM pg_class t "
                    "JOIN pg_index ix ON ix.indrelid = t.oid "
                    "JOIN pg_class i ON i.oid = ix.indexrelid "
                    "JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
                    "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                    "WHERE i.relname = ANY(:names) "
                    "GROUP BY i.relname, ix.indisunique"
                ),
                {"names": list(declared)},
            )
        }

    assert migrated == {name: (True, columns) for name, columns in declared.items()}


async def test_the_shape_read_is_served_by_the_index_that_guarantees_the_same_rule(
    sessions: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    owner: UserRecord,
    statements: StatementRecorder,
) -> None:
    # An index can exist and serve nothing. The claim is about the plan the database produces for
    # the statement the repository sent, so the statement is the recorded one rather than a copy,
    # and the table is grown past the size where reading it whole is cheaper.
    #
    # The index is named from the rule's own columns rather than from the constant the write path
    # passes, so this describes the guarantee (one shape per tenant per day type) rather than a
    # name, and a constant repointed at another index cannot make it agree.
    serves_the_rule = the_unique_index_over(TemplateRow, (TENANT_ID_COLUMN, "day_type_id"))
    day_type_ids = await a_tenant_holding_many_shapes(sessions, owner)
    statements.statements.clear()
    async with sessions() as session:
        await TemplateRepository(session, owner.tenant_id).find_by_day_type(day_type_ids[0])

    sent = next((one for one in statements.statements if one.startswith("SELECT templates")), None)
    assert sent is not None, (
        f"the read sent no statement this test recognises: {statements.statements}"
    )
    # The parameters are positional in the statement the driver received, so the order this test
    # passes them in is pinned rather than assumed: swapped, both are UUIDs and nothing would
    # complain.
    assert sent.index(f"{TENANT_ID_COLUMN} = $1") < sent.index("day_type_id = $2"), sent

    async with engine.connect() as connection:
        plan = await connection.exec_driver_sql(
            f"EXPLAIN {sent}", (owner.tenant_id, day_type_ids[0])
        )
        drawn = "\n".join(str(line[0]) for line in plan)

    assert serves_the_rule in drawn, drawn


async def a_tenant_holding_many_shapes(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> list[UUID]:
    """One day type and one shape per row, at a size where reading the table whole is not free."""
    day_type_ids = [uuid4() for _ in range(ROWS_THE_CHOICE_IS_REAL_AT)]
    async with sessions() as session, session.begin():
        await session.execute(
            insert(DayTypeRow),
            [
                {
                    "id": day_type_id,
                    "tenant_id": owner.tenant_id,
                    "name": f"Day type {at}",
                    "created_at": NOW,
                }
                for at, day_type_id in enumerate(day_type_ids)
            ],
        )
        await session.execute(
            insert(TemplateRow),
            [
                {
                    "id": uuid4(),
                    "tenant_id": owner.tenant_id,
                    "day_type_id": day_type_id,
                    "name": f"Shape {at}",
                    "created_at": NOW,
                }
                for at, day_type_id in enumerate(day_type_ids)
            ],
        )
    async with sessions() as session:
        await session.execute(text("ANALYZE day_types, templates"))
    return day_type_ids


# --------------------------------------------------------------------------------
# The same race at the wire, through the app a process builds
# --------------------------------------------------------------------------------


@pytest.fixture
async def wired(
    live_database_url: str, settings: ServiceSettings
) -> AsyncIterator[httpx.AsyncClient]:
    async with wired_app(live_database_url, settings) as client:
        yield client


async def test_a_raced_declaration_answers_the_unraced_body_at_the_wire(
    wired: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every layer between the refusal and the caller: the app's own dependencies build the
    # service, the request's transaction commits or rolls back, and the registered handler renders
    # what the client reads. Nothing is overridden. The seam is a wrapper around the real read
    # that holds the window open for the FIRST reader only, so the second request runs through it
    # untouched and the restated read is not made to wait for an event already set.
    window = Window(hold_for=WINDOW_SECONDS)
    listing = DayTypeRepository.list_all

    async def list_all_inside_the_window(repository: DayTypeRepository) -> object:
        found = await listing(repository)
        if window.reads == 0:
            await window.hold()
        else:
            window.reads += 1
        return found

    monkeypatch.setattr(DayTypeRepository, "list_all", list_all_inside_the_window)
    headers = await signed_in(wired, owner)
    declare = {"name": A_NAME}

    async def take_the_name() -> httpx.Response:
        await window.open.wait()
        answered = await wired.post(DAY_TYPES_PREFIX, json=declare, headers=headers)
        window.closed.set()
        return answered

    loser, winner = await asyncio.wait_for(
        asyncio.gather(
            wired.post(DAY_TYPES_PREFIX, json=declare, headers=headers), take_the_name()
        ),
        timeout=WINDOW_SECONDS * 2,
    )

    assert winner.status_code == HTTPStatus.CREATED, winner.text
    assert loser.status_code == HTTPStatus.CONFLICT, loser.text
    assert loser.headers["content-type"] == PROBLEM_JSON_MEDIA_TYPE
    unraced = await wired.post(DAY_TYPES_PREFIX, json=declare, headers=headers)
    assert unraced.status_code == HTTPStatus.CONFLICT, unraced.text
    assert without_the_correlation_id(loser) == without_the_correlation_id(unraced)
    assert loser.json()["type"] == "syncr:conflict"

    listed = await wired.get(DAY_TYPES_PREFIX, headers=headers)
    assert [row["name"] for row in listed.json()["dayTypes"]] == [A_NAME]


def without_the_correlation_id(answered: httpx.Response) -> dict[str, Any]:
    """A problem body without the one member that differs per request."""
    return {key: value for key, value in answered.json().items() if key != "instance"}
