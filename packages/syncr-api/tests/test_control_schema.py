"""The per-run schema the control tables are created in.

Two properties matter and neither holds by construction: that two runs against one database
create the control table without colliding, and that a run killed before its teardown leaves
the shared schema as it found it, where a leftover table reads as a table to drop.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from syncr_api.core.db import create_db_engine
from tests.control_models import ScopedThing, table_of
from tests.control_schema import (
    SCHEMA_PREFIX,
    STALE_AFTER,
    create_engine_in_schema,
    created_at,
    new_schema_name,
    run_schema,
    stale_schemas,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine

NOW = datetime(2026, 8, 13, 9, 30, tzinfo=UTC)

SCHEMAS_HOLDING = "SELECT schemaname FROM pg_tables WHERE tablename = :table"
SCHEMA_NAMES = "SELECT nspname FROM pg_namespace"
# The schema an unscoped connection resolves a bare name in, which is the one Alembic's
# autogenerate diffs and the one a concurrent run must never find the control table in.
DEFAULT_SCHEMA = "SELECT current_schema()"

# No run of this suite creates a control table in the shared schema, and the sweep only reads
# the schemas it made, so it cannot clear one that is there. What puts one there is a run of an
# older revision of this suite, killed between its create and its drop, on a database that
# outlives a run. Said here because this is where that residue surfaces.
SHARED_SCHEMA_RESIDUE = (
    "a control table is in the shared schema. This suite never puts one there: an older "
    "revision of it did, and a run killed before its teardown left it behind. Drop it with "
    "`DROP TABLE IF EXISTS public.scoped_things, public.unscoped_things;` and run again."
)


@pytest.fixture
def a_run(live_database_url: str) -> Iterator[str]:
    """One run's schema, created and dropped the way a run does it."""
    with run_schema(live_database_url) as schema:
        yield schema


@pytest.fixture
def a_second_run(live_database_url: str) -> Iterator[str]:
    """A second run's schema, live at the same time as the first."""
    with run_schema(live_database_url) as schema:
        yield schema


async def read(database_url: str, statement: str, **parameters: str) -> list[str]:
    """The first column of every row ``statement`` returns, from an unscoped connection."""
    engine = create_db_engine(database_url)
    try:
        async with engine.begin() as connection:
            found = await connection.execute(text(statement), parameters)
            return sorted(str(row[0]) for row in found)
    finally:
        await engine.dispose()


async def execute(database_url: str, statement: str) -> None:
    engine = create_db_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def create_the_control_table(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(table_of(ScopedThing).create)


def test_a_run_schema_name_records_the_instant_it_was_made() -> None:
    assert created_at(new_schema_name(NOW)) == NOW.replace(microsecond=0)


def test_two_runs_starting_in_the_same_second_are_given_different_names() -> None:
    # The instant is what the sweep reads; it is not what makes a name unique, and a second
    # is long enough for two runs to start inside one.
    assert new_schema_name(NOW) != new_schema_name(NOW)


@pytest.mark.parametrize(
    "name",
    [
        "public",
        "syncr_other_1786000000_ab",
        # An instant and a unique part, and nothing saying this module made it. The sweep
        # drops what it reports, so a name it did not make must not parse.
        "1786000000_ab",
        SCHEMA_PREFIX,
        f"{SCHEMA_PREFIX}1786000000",
        f"{SCHEMA_PREFIX}notaninstant_ab",
        # Digits that name no instant. The sweep must answer rather than raise: it reads every
        # schema whose name starts with the prefix, and one it cannot read must not wedge a run.
        f"{SCHEMA_PREFIX}99999999999999999999_ab",
        f"{SCHEMA_PREFIX}253402300800_ab",
    ],
)
def test_a_name_this_module_did_not_make_records_no_instant(name: str) -> None:
    assert created_at(name) is None


def test_a_sweep_reports_the_schema_a_killed_run_left_behind() -> None:
    left_behind = new_schema_name(NOW - STALE_AFTER - timedelta(minutes=1))

    assert stale_schemas([left_behind], NOW) == [left_behind]


def test_a_sweep_leaves_the_schema_of_a_run_that_could_still_be_going() -> None:
    # The control on the sweep. Without the age it would drop a concurrent run's schema out
    # from under it, which is the failure the schema exists to prevent, restated.
    just_started = new_schema_name(NOW)
    nearly_stale = new_schema_name(NOW - STALE_AFTER + timedelta(minutes=1))

    assert stale_schemas([just_started, nearly_stale], NOW) == []


def test_a_sweep_never_reports_a_name_this_module_did_not_make() -> None:
    long_ago = int((NOW - STALE_AFTER - timedelta(days=1)).timestamp())

    assert stale_schemas(["public", f"{long_ago}_ab", "syncr_other_1_ab"], NOW) == []


def test_a_sweep_reads_past_a_name_that_names_no_instant() -> None:
    # The sweep is documented as never fatal, so a name it cannot read is answered rather than
    # raised on: one such schema would otherwise wedge every run against that database.
    left_behind = new_schema_name(NOW - STALE_AFTER - timedelta(minutes=1))

    assert stale_schemas([f"{SCHEMA_PREFIX}99999999999999999999_ab", left_behind], NOW) == [
        left_behind
    ]


@pytest.mark.integration
async def test_two_runs_create_the_control_table_at_the_same_time(
    live_database_url: str, a_run: str, a_second_run: str
) -> None:
    engines = [create_engine_in_schema(live_database_url, run) for run in (a_run, a_second_run)]
    try:
        await asyncio.gather(*(create_the_control_table(engine) for engine in engines))
        holders = await read(live_database_url, SCHEMAS_HOLDING, table=ScopedThing.__tablename__)
        shared = await read(live_database_url, DEFAULT_SCHEMA)
    finally:
        for engine in engines:
            await engine.dispose()

    # Both halves. Each run really did create the table, and neither reached the schema a
    # third run and Alembic read. Other runs of this suite hold the table in schemas of their
    # own at the same time, so what is asserted is these two and the shared one, not the set.
    assert {a_run, a_second_run} <= set(holders)
    assert set(shared).isdisjoint(holders), SHARED_SCHEMA_RESIDUE


@pytest.mark.integration
async def test_a_run_killed_before_its_teardown_leaves_the_shared_schema_untouched(
    live_database_url: str, a_run: str
) -> None:
    engine = create_engine_in_schema(live_database_url, a_run)
    try:
        await create_the_control_table(engine)
    finally:
        await engine.dispose()

    holders = await read(live_database_url, SCHEMAS_HOLDING, table=ScopedThing.__tablename__)
    shared = await read(live_database_url, DEFAULT_SCHEMA)

    assert a_run in holders
    assert set(shared).isdisjoint(holders), SHARED_SCHEMA_RESIDUE


@pytest.mark.integration
def test_two_runs_starting_together_both_get_a_schema(live_database_url: str) -> None:
    # Both sweep the same residue on the way in, so one of them drops a schema the other has
    # already read. Neither may fail over it: a sweep is housekeeping, not the run's business.
    left_behind = new_schema_name(datetime.now(UTC) - STALE_AFTER - timedelta(minutes=1))
    asyncio.run(execute(live_database_url, f'CREATE SCHEMA "{left_behind}"'))

    def start_a_run() -> str:
        with run_schema(live_database_url) as schema:
            return schema

    with ThreadPoolExecutor(max_workers=2) as pool:
        started = [future.result() for future in [pool.submit(start_a_run) for _ in range(2)]]

    assert len(set(started)) == 2
    assert left_behind not in asyncio.run(read(live_database_url, SCHEMA_NAMES))


@pytest.mark.integration
def test_a_new_run_sweeps_the_schema_an_old_run_left_behind(live_database_url: str) -> None:
    left_behind = new_schema_name(datetime.now(UTC) - STALE_AFTER - timedelta(minutes=1))
    asyncio.run(execute(live_database_url, f'CREATE SCHEMA "{left_behind}"'))

    with run_schema(live_database_url) as mine:
        present = asyncio.run(read(live_database_url, SCHEMA_NAMES))

    assert mine in present
    assert left_behind not in present
