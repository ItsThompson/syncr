"""The routine-grid revision against a real Postgres: the refusal, then the constraints.

The revision refuses to run while any stored row is off the fifteen-minute grid, naming every
offending row and field rather than snapping the declaration, and adds the two check constraints
only on a clean reading. Both halves need a real database: the refusal is an upgrade that fails
mid-chain, and the constraints are facts about what Postgres then accepts.

The chain is replayed from nothing onto a scratch database per test, because a revision is a
historical artifact: it runs against databases at its own point in the chain, not against the
head schema this checkout's models describe.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import time
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from syncr_api.core.db import create_db_engine
from syncr_api.core.migrations import ALEMBIC_DIR

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

# The revision under test and its parent: the scan and the constraints run at the child, and the
# off-grid rows are seeded at the parent, where no grid rule exists yet.
PREVIOUS_REVISION = "sr_deploy_03_operation_session"
GRID_REVISION = "sr_intent_03_routine_grid"

ADMIN_URL = "postgresql+asyncpg://syncr:syncr@localhost:5432/syncr"


@pytest.fixture
def scratch_url() -> Iterator[str]:
    """One fresh database per test, dropped afterwards."""
    name = f"syncr_test_grid_{uuid.uuid4().hex[:8]}"
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name

    async def create() -> None:
        engine = create_db_engine(ADMIN_URL)
        try:
            async with engine.connect() as connection:
                autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit.execute(text(f'CREATE DATABASE "{name}"'))
        finally:
            await engine.dispose()

    async def drop() -> None:
        engine = create_db_engine(ADMIN_URL)
        try:
            async with engine.connect() as connection:
                autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        finally:
            await engine.dispose()

    asyncio.run(create())
    try:
        yield url
    finally:
        asyncio.run(drop())


def upgrade_to(url: str, revision: str) -> None:
    """Run the chain up to ``revision`` against ``url``, through the package's own env."""
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(config, revision)
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


def seed_routine(url: str, *, target_time: str, duration: int, minimum: int) -> str:
    """One routine row written directly, as a tenant's stored declaration."""
    identifier = str(uuid.uuid4())
    wall_time = time.fromisoformat(target_time)

    async def write() -> None:
        engine = create_db_engine(url)
        try:
            async with engine.connect() as connection, connection.begin():
                tenant = await connection.scalar(
                    text(
                        "INSERT INTO tenants (id, created_at) "
                        "VALUES (gen_random_uuid(), now()) RETURNING id"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO routines (id, title, target_time, duration_minutes, "
                        "min_duration_minutes, flex_band_minutes, created_at, tenant_id) "
                        "VALUES (:id, 'Sleep', :target, :duration, :minimum, 0, now(), "
                        ":tenant)"
                    ),
                    {
                        "id": uuid.UUID(identifier),
                        "target": wall_time,
                        "duration": duration,
                        "minimum": minimum,
                        "tenant": tenant,
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(write())
    return identifier


def read_column(url: str, statement: str) -> list[str]:
    async def read() -> list[str]:
        engine = create_db_engine(url)
        try:
            async with engine.connect() as connection:
                return [str(row) for row in await connection.scalars(text(statement))]
        finally:
            await engine.dispose()

    return asyncio.run(read())


def test_the_revision_refuses_an_off_grid_row_and_names_it(scratch_url: str) -> None:
    upgrade_to(scratch_url, PREVIOUS_REVISION)
    bad_target = seed_routine(scratch_url, target_time="05:07", duration=480, minimum=480)
    bad_duration = seed_routine(scratch_url, target_time="23:00", duration=50, minimum=15)

    with pytest.raises(RuntimeError, match="Offending rows") as refused:
        upgrade_to(scratch_url, GRID_REVISION)

    message = str(refused.value)
    assert bad_target in message and bad_duration in message
    assert "target_time" in message and "duration_minutes" in message
    # Nothing was snapped: the rows read back exactly as they were stored.
    durations = read_column(scratch_url, "SELECT duration_minutes FROM routines ORDER BY id")
    assert sorted(int(value) for value in durations) == [50, 480]
    targets = read_column(scratch_url, "SELECT target_time::text FROM routines ORDER BY id")
    assert sorted(targets) == ["05:07:00", "23:00:00"]


def test_the_revision_accepts_on_grid_rows_and_the_constraints_then_bite(
    scratch_url: str,
) -> None:
    upgrade_to(scratch_url, PREVIOUS_REVISION)
    seed_routine(scratch_url, target_time="05:00", duration=45, minimum=45)

    upgrade_to(scratch_url, GRID_REVISION)

    checks = read_column(
        scratch_url,
        "SELECT conname FROM pg_constraint WHERE conrelid = 'routines'::regclass AND contype = 'c'",
    )
    assert "ck_routines_target_time_is_on_the_grid" in checks
    assert "ck_routines_durations_land_on_the_grid" in checks

    # Each new constraint refuses its own half, so neither can be silently absent.
    with pytest.raises(Exception, match="target_time_is_on_the_grid"):
        seed_routine(scratch_url, target_time="05:07", duration=45, minimum=45)
    with pytest.raises(Exception, match="durations_land_on_the_grid"):
        seed_routine(scratch_url, target_time="05:00", duration=50, minimum=45)
