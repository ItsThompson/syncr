"""The pin objective-delta nullability revision against a real Postgres."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta
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

PREVIOUS_REVISION = "sr_plan_20_charged_misses"
PIN_DELTA_REVISION = "sr_plan_02_pin_delta"
ADMIN_URL = "postgresql+asyncpg://syncr:syncr@localhost:5432/syncr"  # pragma: allowlist secret


@pytest.fixture
def scratch_url() -> Iterator[str]:
    """One fresh database per test, dropped afterwards."""
    name = f"syncr_test_pin_delta_{uuid.uuid4().hex[:8]}"
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
    """Run the chain up to ``revision`` against ``url``."""
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(config, revision)
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


def insert_pin(url: str, *, objective_delta: float | None) -> None:
    """Insert one otherwise-complete pin directly into the table."""
    now = datetime.now().astimezone()

    async def insert() -> None:
        engine = create_db_engine(url)
        try:
            async with engine.connect() as connection, connection.begin():
                tenant_id = await connection.scalar(
                    text(
                        "INSERT INTO tenants (id, created_at) "
                        "VALUES (gen_random_uuid(), :created_at) RETURNING id"
                    ),
                    {"created_at": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO pins ("
                        "id, tenant_id, iso_week, block_id, binding, starts_at, ends_at, "
                        "superseded_starts_at, superseded_ends_at, objective_delta, "
                        "weight_set_version, created_at"
                        ") VALUES ("
                        "gen_random_uuid(), :tenant_id, '2026-W35', :block_id, "
                        "'{}'::jsonb, :starts_at, :ends_at, :superseded_starts_at, "
                        ":superseded_ends_at, :objective_delta, 1, :created_at"
                        ")"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "block_id": "0" * 64,
                        "starts_at": now,
                        "ends_at": now + timedelta(minutes=30),
                        "superseded_starts_at": now,
                        "superseded_ends_at": now + timedelta(minutes=30),
                        "objective_delta": objective_delta,
                        "created_at": now,
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())


def test_the_pin_delta_migration_refuses_a_null_delta(scratch_url: str) -> None:
    upgrade_to(scratch_url, PREVIOUS_REVISION)
    upgrade_to(scratch_url, PIN_DELTA_REVISION)

    with pytest.raises(Exception, match="objective_delta"):
        insert_pin(scratch_url, objective_delta=None)
