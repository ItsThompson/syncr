"""The task-chunk-grid revision against a real Postgres: the refusal, then the constraint.

The revision refuses to run while any stored task carries a minimum chunk off the fifteen-minute
grid, naming every offending row rather than snapping the value, and replaces
``min_chunk_minutes_is_a_duration`` with the multiple only on a clean reading. Both halves need a
real database: the refusal is an upgrade that fails mid-chain, and the constraint is a fact about
what Postgres then accepts.

The chain is replayed from nothing onto a scratch database per module, because a revision is a
historical artifact: it runs against databases at its own point in the chain, not against the
head schema this checkout's models describe.
"""

from __future__ import annotations

import asyncio
import os
import uuid
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

# The revision under test and its parent: the scan and the constraint run at the child, and the
# off-grid chunk is seeded at the parent, where no grid rule exists yet.
PREVIOUS_REVISION = "sr_intent_03_routine_grid"
GRID_REVISION = "sr_intent_04_task_grid_floor"

ADMIN_URL = "postgresql+asyncpg://syncr:syncr@localhost:5432/syncr"


@pytest.fixture
def scratch_url() -> Iterator[str]:
    """One fresh database per test, dropped afterwards."""
    name = f"syncr_test_chunk_grid_{uuid.uuid4().hex[:8]}"
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


def seed_task(url: str, *, chunk: int) -> str:
    """One task row written directly, as a tenant's stored declaration."""
    identifier = str(uuid.uuid4())

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
                area = await connection.scalar(
                    text(
                        "INSERT INTO areas (id, name, pigment_index, created_at, tenant_id) "
                        "VALUES (gen_random_uuid(), 'Career', 0, now(), :tenant) RETURNING id"
                    ),
                    {"tenant": tenant},
                )
                await connection.execute(
                    text(
                        "INSERT INTO tasks (id, area_id, title, estimate_minutes, priority, "
                        "min_chunk_minutes, splittable, status, recorded_minutes, created_at, "
                        "tenant_id) "
                        "VALUES (:id, :area, 'Leetcode', 90, 'normal', :chunk, true, 'open', 0, "
                        "now(), :tenant)"
                    ),
                    {
                        "id": uuid.UUID(identifier),
                        "area": area,
                        "chunk": chunk,
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
    bad_chunk = seed_task(scratch_url, chunk=25)

    with pytest.raises(RuntimeError, match=r"Offending rows") as refused:
        upgrade_to(scratch_url, GRID_REVISION)

    message = str(refused.value)
    assert bad_chunk in message
    assert "min_chunk_minutes" in message and "25" in message
    # Nothing was snapped: the row reads back exactly as it was stored.
    chunks = read_column(scratch_url, "SELECT min_chunk_minutes FROM tasks ORDER BY id")
    assert chunks == ["25"]


def test_the_revision_accepts_on_grid_rows_and_the_constraint_then_bites(
    scratch_url: str,
) -> None:
    upgrade_to(scratch_url, PREVIOUS_REVISION)
    seed_task(scratch_url, chunk=45)

    upgrade_to(scratch_url, GRID_REVISION)

    checks = "\n".join(
        read_column(
            scratch_url,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_tasks_min_chunk_minutes_is_a_duration'",
        )
    )
    # The bound the constraint already carried, plus the multiple this revision adds.
    assert "min_chunk_minutes >= " in checks
    assert "min_chunk_minutes <= " in checks
    assert "mod(min_chunk_minutes, " in checks and "= 0" in checks

    # The replaced constraint refuses an off-grid chunk, so the multiple cannot be silently
    # absent.
    with pytest.raises(Exception, match="min_chunk_minutes_is_a_duration"):
        seed_task(scratch_url, chunk=25)
