"""The restore itself, into a database that is not the live one. ``python3 -m ops.restore``.

Two refusals, and both are the same failure written down twice: **a drill that restored into the
database it was dumped from proves nothing and destroys everything.**

- **The target is the live database.** One wrong environment variable in a compose overlay, and the
  drill overwrites production with last night's copy.
- **The target already holds tables.** A restore into a populated database merges: some objects
  fail, others apply, and the result is neither copy.

The live database has to be NAMED for the first refusal to be possible, so both variables are
required. A drill that does not know what production is cannot refuse to write to it.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from ops import environment, postgres
from ops.fetch import FETCHED_DUMP
from ops.process import run as run_command

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ops.environment import Target
    from ops.process import Run

# Tables in the schema a dump restores into, and the revision the restored copy carries.
PUBLIC_TABLE_COUNT = "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
APPLIED_REVISION = "SELECT version_num FROM alembic_version"

EXIT_OK = 0
EXIT_REFUSED = 1


class RestoreRefused(Exception):
    """The restore stopped before it could write to the wrong database."""


def main() -> int:
    """Restore the fetched dump into the scratch database. Returns the process exit status."""
    try:
        revision = restore_fetched(environ=os.environ, run=run_command)
    except Exception as refused:  # noqa: BLE001 - one message and a non-zero exit, whatever failed
        print(f"restore refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"restored, and the copy carries revision {revision}")
    return EXIT_OK


def restore_fetched(*, environ: Mapping[str, str], run: Run) -> str:
    """Restore into the scratch database and report the revision it came back at."""
    paths = environment.paths(environ)
    target = environment.libpq_present(environ)
    refuse_the_live_database(target, environment.live_target(environ))
    require_empty(run=run)

    archive = paths.scratch / FETCHED_DUMP
    if not archive.is_file():
        raise RestoreRefused(f"{archive} does not exist: run `python3 -m ops.fetch` first")
    print(f"restoring {archive} into {target}")
    postgres.restore(archive, database=target.database, run=run)
    return postgres.scalar(APPLIED_REVISION, run=run)


def refuse_the_live_database(target: Target, live: Target) -> None:
    """Refuse when the restore target is the deployment's own database."""
    if (target.host, target.port, target.database) == (live.host, live.port, live.database):
        raise RestoreRefused(
            f"the restore target {target} IS the live database. A drill that restores into the "
            "database it was dumped from proves nothing and overwrites everything. Point "
            "PGHOST/PGDATABASE at the scratch instance."
        )


def require_empty(*, run: Run) -> None:
    """Refuse a target that already holds tables.

    ``pg_restore`` into a populated database applies what it can and fails the rest, so the result
    is neither the copy nor what was there before. It is also the shape a second drill run would
    take against a target somebody forgot to drop.
    """
    stated = postgres.scalar(PUBLIC_TABLE_COUNT, run=run)
    if stated != "0":
        raise RestoreRefused(
            f"the restore target already holds {stated} tables in `public`. Drop and recreate it: "
            "`just restore-drill` does that with `docker compose down -v` on the scratch instance."
        )


if __name__ == "__main__":
    sys.exit(main())
