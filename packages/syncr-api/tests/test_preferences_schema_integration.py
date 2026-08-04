"""The preferences table's own constraints, asserted against a hand-written row.

The entity refuses almost every one of these before a request reaches the database, and the service
suite proves that. This proves the backstop: a caller reaching the table from ``psql``, from a later
migration, or from a repository written without the entity is refused by the schema itself.

Two of them are the table's alone and cannot be reached through the entity at all, which is why they
are worth reading. The three unique indexes are what make "one preference per owner" true rather
than something the service remembers, and the ``CASE`` pairing the discriminator with the reference
it names is what stops a row two owners could be read out of. Neither is expressible as an entity
invariant, because the entity holds one owner and not three nullable columns.

Each case is a single-column deviation from a row the table accepts, so a rejection names one
constraint rather than several at once. The control at the top is what makes that meaningful: if the
accepted row stopped being accepted, every rejection below would pass for the wrong reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database
from syncr_api.preferences.config import PREFERENCES_TABLE
from tests.live_tenants import remove_tenant, run, seed_owner

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

_INSERT = text(
    f"INSERT INTO {PREFERENCES_TABLE} ("  # noqa: S608 - a constant table name, no external input
    "id, tenant_id, owner_kind, area_id, habit_id, task_id, windows, strength,"
    " preferred_duration_minutes, max_per_day_minutes, created_at"
    ") VALUES ("
    ":id, :tenant_id, :owner_kind, :area_id, :habit_id, :task_id, CAST(:windows AS jsonb),"
    " :strength, :preferred_duration_minutes, :max_per_day_minutes, :created_at"
    ")"
)

_INSERT_AREA = text(
    "INSERT INTO areas (id, tenant_id, parent_id, name, pigment_index, budget_percent,"
    " floor_hours, default_preference_id, created_at)"
    " VALUES (:id, :tenant_id, NULL, :name, 0, NULL, NULL, NULL, :created_at)"
)

_INSERT_HABIT = text(
    "INSERT INTO habits (id, tenant_id, area_id, title, cadence_kind, cadence_times_per_week,"
    " cadence_approx_days, duration_min_minutes, duration_max_minutes, miss_policy,"
    " binding_source, variants, debt_cap_periods, created_at)"
    " VALUES (:id, :tenant_id, :area_id, 'Gym', 'daily', NULL, NULL, 90, 90, 'forgive', 'fixed',"
    " CAST('[]' AS jsonb), 2, :created_at)"
)

_INSERT_TASK = text(
    "INSERT INTO tasks (id, tenant_id, area_id, project_id, title, estimate_minutes,"
    " recorded_minutes, min_chunk_minutes, splittable, priority, status, deadline, completed_at,"
    " created_at)"
    " VALUES (:id, :tenant_id, :area_id, NULL, 'Essay', 60, 0, 15, true, 'normal', 'open', NULL,"
    " NULL, :created_at)"
)

ONE_WINDOW = '[{"start": "05:30:00", "end": "07:00:00"}]'


class LiveTable:
    """A tenant with one Area, one habit, and one task, and a connection that inserts by hand."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.tenant_id: TenantId = uuid4()
        self.area_id = uuid4()
        self.habit_id = uuid4()
        self.task_id = uuid4()

    def seed(self) -> None:
        async def create() -> TenantId:
            database = create_database(self._database_url)
            try:
                owner = await seed_owner(database.sessionmaker)
                at = utc_now()
                owned = {"tenant_id": owner.tenant_id, "area_id": self.area_id, "created_at": at}
                async with database.sessionmaker() as session, session.begin():
                    await session.execute(
                        _INSERT_AREA,
                        {
                            "id": self.area_id,
                            "tenant_id": owner.tenant_id,
                            "name": f"Fitness {uuid4().hex[:8]}",
                            "created_at": at,
                        },
                    )
                    await session.execute(_INSERT_HABIT, {"id": self.habit_id, **owned})
                    await session.execute(_INSERT_TASK, {"id": self.task_id, **owned})
                return owner.tenant_id
            finally:
                await database.engine.dispose()

        self.tenant_id = run(create())

    def insert(self, **overrides: Any) -> None:
        """Insert one preference row, raising ``DBAPIError`` when a constraint refuses it."""
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": self.tenant_id,
            "owner_kind": "area",
            "area_id": self.area_id,
            "habit_id": None,
            "task_id": None,
            "windows": ONE_WINDOW,
            "strength": "strong",
            "preferred_duration_minutes": 90,
            "max_per_day_minutes": 180,
            "created_at": utc_now(),
        }
        values.update(overrides)

        async def write() -> None:
            database = create_database(self._database_url)
            try:
                async with database.sessionmaker() as session, session.begin():
                    await session.execute(_INSERT, values)
            finally:
                await database.engine.dispose()

        run(write())

    def on_the_habit(self, **overrides: Any) -> dict[str, Any]:
        """The column set for a habit-owned row, which is the shape an override stores."""
        return {
            "owner_kind": "habit",
            "area_id": None,
            "habit_id": self.habit_id,
            "task_id": None,
            "max_per_day_minutes": None,
            **overrides,
        }


@pytest.fixture
def table(live_database_url: str) -> Iterator[LiveTable]:
    live = LiveTable(live_database_url)
    live.seed()
    yield live
    remove_tenant(live_database_url, live.tenant_id)


def test_the_row_every_case_below_deviates_from_is_accepted(table: LiveTable) -> None:
    # The control. Every rejection below changes one column of this row, so if this row stopped
    # being insertable each of them would be refused for a reason the test does not name.
    table.insert()


def test_a_habit_owned_row_is_accepted(table: LiveTable) -> None:
    # The second control, for the override cases: the shape a habit's preference stores.
    table.insert(**table.on_the_habit())


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("an unknown kind of owner", {"owner_kind": "project"}),
        ("an area kind naming no Area", {"owner_kind": "area", "area_id": None}),
        ("a habit kind naming an Area", {"owner_kind": "habit", "habit_id": None}),
        (
            "a row naming two owners",
            {"owner_kind": "area", "habit_id": uuid4()},
        ),
        (
            "a row naming no owner at all",
            {"area_id": None, "habit_id": None, "task_id": None},
        ),
        ("a strength of hard", {"strength": "hard"}),
        ("a strength of none", {"strength": ""}),
        ("windows that are not a list", {"windows": '{"start": "05:30:00"}'}),
        (
            "more windows than a preference names",
            {
                "windows": "["
                + ", ".join(
                    f'{{"start": "{hour:02d}:00:00", "end": "{hour:02d}:30:00"}}'
                    for hour in range(7)
                )
                + "]"
            },
        ),
        ("an ideal session below the grid step", {"preferred_duration_minutes": 10}),
        ("an ideal session past a day", {"preferred_duration_minutes": 1455}),
        ("an ideal session off the grid", {"preferred_duration_minutes": 25}),
        ("a daily cap below one block", {"max_per_day_minutes": 14}),
        ("a daily cap past a day", {"max_per_day_minutes": 1441}),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_the_schema_refuses(table: LiveTable, case: str, overrides: dict[str, Any]) -> None:
    with pytest.raises(DBAPIError):
        table.insert(**overrides)


@pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
def test_a_daily_cap_on_an_override_is_refused_by_the_table(table: LiveTable, kind: str) -> None:
    # X13's backstop. The entity refuses this and the request shape has no field for it, so this is
    # what stops a row carrying one arriving from `psql` or from a later migration.
    owner: dict[str, Any] = {
        "owner_kind": kind,
        "area_id": None,
        "habit_id": None,
        "task_id": None,
    }
    owner[f"{kind}_id"] = table.habit_id if kind == "habit" else table.task_id

    with pytest.raises(DBAPIError):
        table.insert(**owner, max_per_day_minutes=180)


@pytest.mark.parametrize(
    "owner_column", ["area_id", "habit_id", "task_id"], ids=["area", "habit", "task"]
)
def test_one_owner_holds_at_most_one_preference(table: LiveTable, owner_column: str) -> None:
    # The unique indexes, which are what make the PUT a replacement rather than an accumulation.
    # Not expressible as an entity invariant: the entity holds one preference and cannot see a
    # second row for the same owner.
    kind = {"area_id": "area", "habit_id": "habit", "task_id": "task"}[owner_column]
    identifier = {
        "area_id": table.area_id,
        "habit_id": table.habit_id,
        "task_id": table.task_id,
    }[owner_column]
    columns: dict[str, Any] = {
        "owner_kind": kind,
        "area_id": None,
        "habit_id": None,
        "task_id": None,
        "max_per_day_minutes": 180 if kind == "area" else None,
        owner_column: identifier,
    }
    table.insert(**columns)

    with pytest.raises(DBAPIError):
        table.insert(**columns)


@pytest.mark.parametrize(
    "owner_column", ["area_id", "habit_id", "task_id"], ids=["area", "habit", "task"]
)
def test_an_owner_that_does_not_exist_cannot_be_named(table: LiveTable, owner_column: str) -> None:
    # The foreign keys, which are why the owner is three references rather than one untyped
    # identifier: a preference addressed to a row that no longer exists would be a window the
    # resolution reads after the user deleted the thing it belonged to.
    kind = {"area_id": "area", "habit_id": "habit", "task_id": "task"}[owner_column]
    columns: dict[str, Any] = {
        "owner_kind": kind,
        "area_id": None,
        "habit_id": None,
        "task_id": None,
        "max_per_day_minutes": 180 if kind == "area" else None,
        owner_column: uuid4(),
    }

    with pytest.raises(DBAPIError):
        table.insert(**columns)
