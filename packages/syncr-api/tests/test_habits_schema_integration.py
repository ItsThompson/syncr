"""The habits table's own constraints, asserted against a hand-written row.

The entity refuses every one of these before a request reaches the database, and the service
suite proves that. This proves the backstop: a caller reaching the table from ``psql``, from a
later migration, or from a repository written without the entity is refused by the schema itself.

Each case is a single-column deviation from a row the table accepts, so a rejection names one
constraint rather than several at once. The control at the top is what makes that meaningful: if
the accepted row stopped being accepted, every rejection below would pass for the wrong reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database
from syncr_api.habits.config import HABITS_TABLE
from tests.live_tenants import remove_tenant, run, seed_owner

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

_INSERT = text(
    f"INSERT INTO {HABITS_TABLE} ("  # noqa: S608 - a constant table name, no external input
    "id, tenant_id, area_id, title, cadence_kind, cadence_times_per_week, cadence_approx_days,"
    " duration_min_minutes, duration_max_minutes, miss_policy, binding_source, variants,"
    " debt_cap_periods, charged_misses, created_at"
    ") VALUES ("
    ":id, :tenant_id, :area_id, :title, :cadence_kind, :cadence_times_per_week,"
    " :cadence_approx_days, :duration_min_minutes, :duration_max_minutes, :miss_policy,"
    " :binding_source, CAST(:variants AS jsonb), :debt_cap_periods, :charged_misses, :created_at"
    ")"
)

_INSERT_AREA = text(
    "INSERT INTO areas (id, tenant_id, parent_id, name, pigment_index, budget_percent,"
    " floor_hours, created_at)"
    " VALUES (:id, :tenant_id, NULL, :name, 0, NULL, NULL, :created_at)"
)


class LiveTable:
    """A tenant, an Area, and a connection that inserts habit rows by hand."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.tenant_id: TenantId = uuid4()
        self.area_id = uuid4()

    def seed(self) -> None:
        async def create() -> TenantId:
            database = create_database(self._database_url)
            try:
                owner = await seed_owner(database.sessionmaker)
                async with database.sessionmaker() as session, session.begin():
                    await session.execute(
                        _INSERT_AREA,
                        {
                            "id": self.area_id,
                            "tenant_id": owner.tenant_id,
                            "name": f"Fitness {uuid4().hex[:8]}",
                            "created_at": utc_now(),
                        },
                    )
                return owner.tenant_id
            finally:
                await database.engine.dispose()

        self.tenant_id = run(create())

    def insert(self, **overrides: Any) -> None:
        """Insert one habit row, raising ``DBAPIError`` when a constraint refuses it."""
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": self.tenant_id,
            "area_id": self.area_id,
            "title": "Gym",
            "cadence_kind": "times_per_week",
            "cadence_times_per_week": 4,
            "cadence_approx_days": None,
            "duration_min_minutes": 90,
            "duration_max_minutes": 90,
            "miss_policy": "forgive",
            "binding_source": "fixed",
            "variants": "[]",
            "debt_cap_periods": 2,
            "charged_misses": 0,
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


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("an unknown cadence kind", {"cadence_kind": "monthly"}),
        (
            "a count on a daily cadence",
            {"cadence_kind": "daily", "cadence_times_per_week": 4},
        ),
        (
            "a daily cadence carrying an interval",
            {"cadence_kind": "daily", "cadence_times_per_week": None, "cadence_approx_days": 7},
        ),
        (
            "a count-per-week cadence with no count",
            {"cadence_times_per_week": None},
        ),
        (
            "a cadence carrying both numbers",
            {"cadence_approx_days": 7},
        ),
        (
            "an interval cadence with no interval",
            {"cadence_kind": "every_approx_days", "cadence_times_per_week": None},
        ),
        ("a count per week of zero", {"cadence_times_per_week": 0}),
        ("a count per week past the bound", {"cadence_times_per_week": 169}),
        (
            "an interval of one day",
            {
                "cadence_kind": "every_approx_days",
                "cadence_times_per_week": None,
                "cadence_approx_days": 1,
            },
        ),
        (
            "an interval past the bound",
            {
                "cadence_kind": "every_approx_days",
                "cadence_times_per_week": None,
                "cadence_approx_days": 366,
            },
        ),
        ("a duration below the grid step", {"duration_min_minutes": 0, "duration_max_minutes": 0}),
        ("a duration past a day", {"duration_min_minutes": 1455, "duration_max_minutes": 1455}),
        ("a duration off the grid", {"duration_min_minutes": 25, "duration_max_minutes": 25}),
        ("a ceiling off the grid", {"duration_max_minutes": 100}),
        ("a duration that runs backwards", {"duration_min_minutes": 120}),
        ("an unknown miss policy", {"miss_policy": "postpone"}),
        ("an unknown binding source", {"binding_source": "backlog"}),
        ("a rotation with no variants", {"binding_source": "rotation"}),
        ("a fixed habit carrying variants", {"variants": '["Legs"]'}),
        ("a queue habit carrying variants", {"binding_source": "queue", "variants": '["Legs"]'}),
        (
            "a rotation longer than a rotation holds",
            {
                "binding_source": "rotation",
                "variants": "[" + ", ".join(f'"Day {index}"' for index in range(25)) + "]",
            },
        ),
        ("variants that are not a list", {"variants": '{"first": "Legs"}'}),
        ("a debt cap of zero", {"debt_cap_periods": 0}),
        ("a debt cap past the bound", {"debt_cap_periods": 53}),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_the_schema_refuses(table: LiveTable, case: str, overrides: dict[str, Any]) -> None:
    with pytest.raises(DBAPIError):
        table.insert(**overrides)


def test_an_area_that_does_not_exist_cannot_be_named(table: LiveTable) -> None:
    with pytest.raises(DBAPIError):
        table.insert(area_id=uuid4())


def test_a_tenant_that_does_not_exist_cannot_be_named(table: LiveTable) -> None:
    with pytest.raises(DBAPIError):
        table.insert(tenant_id=uuid4())
