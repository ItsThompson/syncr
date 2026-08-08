#!/usr/bin/env python3
"""Empty every domain table, so the next seed starts from a database with a schema and no rows.

Run as a one-shot in the api image, which is where the driver and the settings live::

    docker compose -f docker-compose.yml -f e2e/docker-compose.e2e.yml \\
      run --rm --no-deps worker python /harness/reset.py

TRUNCATE RATHER THAN A DROP AND A RE-MIGRATE. The schema a scenario runs against must be the
one the migrations produce, and re-running them per fixture would make every seed pay for
fifty-one revisions. Truncating leaves ``alembic_version`` alone, so ``/readyz`` still compares
the same head it did before.

IT REFUSES A DATABASE THAT IS NOT THIS STACK'S. The e2e stack keeps Postgres on an internal
network with no published port precisely because a host-local Postgres shadows a compose route,
and this script is the one that would empty whatever it reached. So it reads the host out of the
URL and refuses anything but the in-network service name.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Final

from sqlalchemy import text

from syncr_api.core.db import create_database
from syncr_api.core.settings import EnvSettings

# The service name the compose file gives Postgres. A URL naming anything else is either a host
# database or the dev stack's, and emptying either from here would be the most expensive mistake
# this harness could make.
IN_NETWORK_HOST: Final = "@postgres:"

VERSION_TABLE: Final = "alembic_version"

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1


async def run(database_url: str) -> int:
    """Empty every table but the migration marker, and report how many were emptied."""
    if IN_NETWORK_HOST not in database_url:
        print(
            f"refused: DATABASE_URL does not name the in-network Postgres ({IN_NETWORK_HOST!r}), "
            "so this is not the e2e stack's database and this script will not empty it",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    database = create_database(database_url)
    try:
        async with database.engine.begin() as connection:
            rows = await connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> :version"
                ),
                {"version": VERSION_TABLE},
            )
            tables = sorted(row[0] for row in rows)
            if not tables:
                print("refused: no tables to empty; run the migrations first", file=sys.stderr)
                return EXIT_REFUSED
            quoted = ", ".join(f'"{table}"' for table in tables)
            await connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    finally:
        await database.engine.dispose()

    print(f"emptied {len(tables)} tables")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(asyncio.run(run(EnvSettings().database_url)))
