"""The preferences table's own constraints, asserted against a hand-written row.

The entity refuses almost every one of these before a request reaches the database, and the service
suite proves that. This proves the backstop: a caller reaching the table from ``psql``, from a later
migration, or from a repository written without the entity is refused by the schema itself.

Two of them are the table's alone and cannot be reached through the entity at all, which is why they
are worth reading. The three unique indexes are what make "one preference per owner" true rather
than something the service remembers, and the ``CASE`` pairing the discriminator with the reference
it names is what stops a row two owners could be read out of. Neither is expressible as an entity
invariant, because the entity holds one owner and not three nullable columns.

Each case deviates from a row the table accepts by one RULE, and each asserts the CONSTRAINT NAME
rather than only the status. Without the name, a case that deviates on two rules passes on whichever
fires first and goes on passing after the rule it names is dropped, which is exactly what one case
here was doing. Two cases accept either of two names and each says why at the site: an unknown owner
kind necessarily fails the ``CASE`` pairing as well as the vocabulary, and a malformed window list
can abort on ``jsonb_array_length`` before the shape constraint names itself.

The two controls at the top are what make all of that meaningful: if an accepted row stopped being
accepted, every rejection below would pass for the wrong reason.
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
    " floor_hours, created_at)"
    " VALUES (:id, :tenant_id, NULL, :name, 0, NULL, NULL, :created_at)"
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


_OWNER_PAIRING = "ck_preferences_exactly_one_owner_and_it_is_the_kind_named"
_KIND_VOCABULARY = "ck_preferences_owner_kind_is_known"
_STRENGTH_VOCABULARY = "ck_preferences_a_strength_is_strong_or_soft_and_never_hard"
_WINDOWS_ARE_A_LIST = "ck_preferences_windows_is_an_ordered_list"
_WINDOW_COUNT = "ck_preferences_a_preference_names_a_few_times_of_day"
_IDEAL_SESSION = "ck_preferences_an_ideal_session_lands_on_the_snap_grid"
_CAP_IS_AN_AREAS = "ck_preferences_a_daily_cap_belongs_to_an_area"
_CAP_BOUNDS = "ck_preferences_a_daily_cap_admits_at_least_one_block"

# `jsonb_array_length` RAISES on a non-array rather than returning false, so on a malformed window
# list the count constraint can abort the statement before the shape constraint names itself. Which
# of the two speaks is Postgres's evaluation order, which is not declared, so both are accepted.
_NOT_AN_ARRAY = "cannot get array length of a non-array"


@pytest.mark.parametrize(
    ("case", "overrides", "refused_by"),
    [
        # Four characters, not `project`: `owner_kind` is varchar(5), so a longer value is refused
        # by the column width and would prove that rather than the vocabulary. The cap is nulled
        # for the reason the habit case below nulls it: a non-area kind may not carry one, so
        # leaving the base row's 180 would fire the cap's constraint instead of either kind rule.
        (
            "an unknown kind of owner",
            {"owner_kind": "goal", "max_per_day_minutes": None},
            (_OWNER_PAIRING, _KIND_VOCABULARY),
        ),
        ("an area kind naming no Area", {"owner_kind": "area", "area_id": None}, (_OWNER_PAIRING,)),
        (
            "a habit kind naming an Area",
            # The cap is nulled as well as the kind changed, and that is not a second deviation: a
            # habit-owned row may not carry one at all, so leaving the base row's 180 would fire
            # the cap's constraint and this case would pass with the owner pairing dropped.
            {"owner_kind": "habit", "habit_id": None, "max_per_day_minutes": None},
            (_OWNER_PAIRING,),
        ),
        ("a row naming two owners", {"owner_kind": "area", "habit_id": uuid4()}, (_OWNER_PAIRING,)),
        (
            "a row naming no owner at all",
            {"area_id": None, "habit_id": None, "task_id": None},
            (_OWNER_PAIRING,),
        ),
        ("a strength of hard", {"strength": "hard"}, (_STRENGTH_VOCABULARY,)),
        ("a strength of none", {"strength": ""}, (_STRENGTH_VOCABULARY,)),
        (
            "windows that are not a list",
            {"windows": '{"start": "05:30:00"}'},
            (_WINDOWS_ARE_A_LIST, _NOT_AN_ARRAY),
        ),
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
            (_WINDOW_COUNT,),
        ),
        (
            "an ideal session below the grid step",
            {"preferred_duration_minutes": 10},
            (_IDEAL_SESSION,),
        ),
        ("an ideal session past a day", {"preferred_duration_minutes": 1455}, (_IDEAL_SESSION,)),
        ("an ideal session off the grid", {"preferred_duration_minutes": 25}, (_IDEAL_SESSION,)),
        ("a daily cap below one block", {"max_per_day_minutes": 14}, (_CAP_BOUNDS,)),
        ("a daily cap past a day", {"max_per_day_minutes": 1441}, (_CAP_BOUNDS,)),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_the_schema_refuses(
    table: LiveTable, case: str, overrides: dict[str, Any], refused_by: tuple[str, ...]
) -> None:
    # The CONSTRAINT is asserted, not only the status. Without that, a case deviating on two columns
    # passes on whichever rule fires first and would go on passing after the rule it names is
    # dropped, which is exactly what one case here was doing.
    with pytest.raises(DBAPIError) as refused:
        table.insert(**overrides)

    assert any(named in str(refused.value) for named in refused_by), str(refused.value)


@pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
def test_a_daily_cap_on_an_override_is_refused_by_the_table(table: LiveTable, kind: str) -> None:
    # The backstop for the Area-only cap. The entity refuses this and the request shape has no field
    # for it, so this is what stops a row carrying one arriving from `psql` or from a later
    # migration.
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
