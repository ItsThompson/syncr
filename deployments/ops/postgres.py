"""The three Postgres binaries this path uses, each as one narrow call.

Version-matched by construction: the image these run in is built FROM the pinned
``postgres:16.10-bookworm``, so the ``pg_dump`` that writes an archive and the server that will
restore it are the same build. A dump written by a newer ``pg_dump`` than the target server is a
dump the server may refuse, and discovering that during a recovery is discovering it at the worst
moment.

Credentials are never arguments. ``libpq`` reads them from the environment, so nothing here can put
a password in a process listing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

    from ops.process import Run

PG_DUMP: Final = "pg_dump"
PG_RESTORE: Final = "pg_restore"
PSQL: Final = "psql"

# `-At` is unaligned, tuples-only: one value per line and no header, so a caller reads a scalar
# without parsing a table.
_SCALAR_FLAGS: Final = ("-At", "--no-psqlrc")


def dump(into: Path, *, run: Run, pg_dump: str = PG_DUMP) -> Path:
    """Write a compressed custom-format archive of the configured database.

    ``--file`` rather than standard output, deliberately. Through a pipe, the writer's exit status
    is lost and a closed pipe produces a short file with a zero status from the reader's side, which
    is the "succeeded and wrote nothing" shape the verification exists to catch. With ``--file``,
    ``pg_dump``'s own status covers the whole write.
    """
    run([pg_dump, "--format=custom", "--compress=9", "--file", str(into)])
    return into


def listing(archive: Path, *, run: Run, pg_restore: str = PG_RESTORE) -> str:
    """The archive's table of contents, as text.

    Its EXIT STATUS is half the reading: a truncated archive has an intact header, so nothing about
    the first bytes of a file says the rest of it arrived. ``pg_restore --list`` reads to the end.
    """
    return run([pg_restore, "--list", str(archive)]).stdout


def restore(archive: Path, *, database: str, run: Run, pg_restore: str = PG_RESTORE) -> None:
    """Restore an archive into ``database``, stopping at the first error.

    ``--dbname`` is not optional and not a convenience: WITHOUT IT ``pg_restore`` WRITES SQL TO
    STANDARD OUTPUT and exits 0, having connected to nothing and restored nothing. A drill built on
    the environment's default database would pass with an empty target every time.

    ``--exit-on-error`` is also not the default: ``pg_restore`` otherwise reports each error,
    carries on, and exits 0, so a partial restore reads as a successful one.

    ``--no-owner`` and ``--no-privileges`` because the scratch database's role is not the
    deployment's, and a grant to a role that does not exist would stop the restore for a reason that
    has nothing to do with the data.
    """
    run(
        [
            pg_restore,
            "--dbname",
            database,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            str(archive),
        ]
    )


def scalar(statement: str, *, run: Run, psql: str = PSQL) -> str:
    """One value from one statement, with no header and no alignment."""
    return run([psql, *_SCALAR_FLAGS, "-c", statement]).stdout.strip()
