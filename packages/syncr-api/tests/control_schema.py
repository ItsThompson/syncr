"""The Postgres schema the control tables are created in, one per test run.

The control tables are created and dropped per test, and the rules that read them assert
their names unqualified, so the names cannot carry a per-run suffix. A schema does the same
work without touching a name: two runs against one database each create ``scoped_things``
in a schema of their own instead of colliding on one in the shared schema.

The schema is carried on the connection's ``search_path``, so an unqualified name resolves
in the run's schema first and falls through to ``public`` for the real tables a control
table's foreign key points at.

A schema a killed run left behind is also invisible to Alembic's autogenerate, which diffs
the default schema alone, where a leftover table in the shared schema reads as a table to
drop.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from syncr_api.core.db import create_db_engine

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine

SCHEMA_PREFIX = "syncr_control_"

# How old a schema has to be before another run reads it as residue rather than as a live
# run's own. A run is minutes; the margin is what stops a sweep from dropping the schema
# out from under a run that is still going.
STALE_AFTER = timedelta(hours=6)

_SCHEMAS_LIKE_OURS = text("SELECT nspname FROM pg_namespace WHERE nspname LIKE :pattern")


def new_schema_name(now: datetime) -> str:
    """A schema name for one run, carrying the instant it was made."""
    return f"{SCHEMA_PREFIX}{int(now.timestamp())}_{uuid4().hex[:8]}"


def created_at(name: str) -> datetime | None:
    """The instant ``name`` records, or ``None`` when it is not one of these names."""
    if not name.startswith(SCHEMA_PREFIX):
        return None
    stamp, _, unique = name.removeprefix(SCHEMA_PREFIX).partition("_")
    if not stamp.isdigit() or not unique:
        return None
    return datetime.fromtimestamp(int(stamp), tz=UTC)


def stale_schemas(names: Iterable[str], now: datetime) -> list[str]:
    """The run schemas old enough that no live run can still own them.

    A name this module did not make is never reported, so a sweep can only ever drop what
    a previous run of these tests created.
    """
    cutoff = now - STALE_AFTER
    return sorted(
        name for name in names if (made := created_at(name)) is not None and made < cutoff
    )


@contextmanager
def run_schema(database_url: str) -> Iterator[str]:
    """Create this run's control schema, hand out its name, and drop it on the way out.

    Residue from a run that was killed before its teardown is swept on the way in, which is
    the only place a later run can do it: the killed run is gone.
    """
    schema = new_schema_name(datetime.now(UTC))
    asyncio.run(_create(database_url, schema))
    try:
        yield schema
    finally:
        asyncio.run(_drop(database_url, schema))


def create_engine_in_schema(database_url: str, schema: str) -> AsyncEngine:
    """An engine whose every transaction resolves an unqualified name in ``schema`` first.

    The path is set per transaction rather than once per connection because Postgres rolls
    a plain ``SET`` back with the transaction it ran in, and these tests roll back.
    """
    engine = create_db_engine(database_url)
    path = f"{_quoted(engine, schema)}, public"

    @event.listens_for(engine.sync_engine, "begin")
    def _scope_to_the_run_schema(connection: Connection) -> None:
        connection.exec_driver_sql(f"SET LOCAL search_path TO {path}")

    return engine


def _quoted(engine: AsyncEngine, schema: str) -> str:
    return engine.dialect.identifier_preparer.quote(schema)


async def _create(database_url: str, schema: str) -> None:
    engine = create_db_engine(database_url)
    try:
        await _sweep(engine)
        async with engine.begin() as connection:
            await connection.execute(text(f"CREATE SCHEMA {_quoted(engine, schema)}"))
    finally:
        await engine.dispose()


async def _drop(database_url: str, schema: str) -> None:
    engine = create_db_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(f"DROP SCHEMA IF EXISTS {_quoted(engine, schema)} CASCADE")
            )
    finally:
        await engine.dispose()


async def _sweep(engine: AsyncEngine) -> None:
    """Drop the residue, one schema per transaction and never fatally.

    Two runs starting together read the same residue and both try to drop it, so a drop that
    finds the schema already gone is the ordinary case rather than a failure. What a lost race
    leaves behind is inert, and the next run reads it again.
    """
    async with engine.connect() as connection:
        found = await connection.execute(_SCHEMAS_LIKE_OURS, {"pattern": f"{SCHEMA_PREFIX}%"})
        residue = stale_schemas([row[0] for row in found], datetime.now(UTC))
    for stale in residue:
        with suppress(SQLAlchemyError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(f"DROP SCHEMA IF EXISTS {_quoted(engine, stale)} CASCADE")
                )
