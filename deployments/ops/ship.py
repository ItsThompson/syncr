"""WAL segments to the same bucket, once a minute. ``python3 -m ops.ship``.

Postgres's ``archive_command`` copies a completed segment into a staging volume; this compresses it,
encrypts it, uploads it, and removes the local copy. The recovery point is therefore bounded by
``archive_timeout`` plus this interval, which is the arithmetic ``ops.config`` states.

**The freshness gauge is written only when Postgres itself says archiving is working.** Draining an
empty staging directory looks identical to a healthy deployment and to one whose ``archive_command``
has been failing for a week: in the second case the segments never reach the volume at all, and a
shipper that published a fresh timestamp for an empty directory would report a five-minute recovery
point while none existed. ``pg_stat_archiver`` is the server's own record of that, so it is read
first, and a pending failure is the one condition that refuses.

Segments are shipped OLDEST FIRST and each is removed only after its upload returns. A recovery
replays them in order, so a gap is worse than a delay: stopping at the first failure leaves a
contiguous prefix off-host and the rest still on the volume.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ops import crypto, environment, postgres
from ops.config import ENCRYPTED_SUFFIX, WAL_METRIC, WAL_STAGING_DIR
from ops.exposition import write_gauge
from ops.prepare import writable_by_postgres
from ops.process import run as run_command
from ops.remote import Remote, off_host_or_refused

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ops.process import Run

EXIT_OK = 0
EXIT_REFUSED = 1

# `pg_stat_archiver` in one row: what has been archived, what failed, and when each last happened.
ARCHIVER_STATE = (
    "SELECT archived_count, coalesce(last_archived_time::text, ''), failed_count, "
    "coalesce(last_failed_time::text, '') FROM pg_stat_archiver"
)

# What the compressor leaves behind while it works, and what a previous run may have left. Neither
# is a segment to ship.
_NOT_A_SEGMENT = (".gz", ENCRYPTED_SUFFIX, ".tmp", ".partial", ".history")


class ArchivingFailing(Exception):
    """Postgres reports its own archive_command failing, so an empty volume proves nothing."""


def main() -> int:
    """Ship whatever is staged. Returns the process exit status."""
    try:
        shipped = ship(environ=os.environ, run=run_command)
    except Exception as refused:  # noqa: BLE001 - one message and a non-zero exit, whatever failed
        print(f"WAL shipping refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"shipped {shipped} WAL segments")
    return EXIT_OK


def ship(*, environ: Mapping[str, str], run: Run) -> int:
    """Ship every staged segment and publish the freshness gauge. Returns how many were shipped."""
    now = datetime.now(tz=UTC)
    paths = environment.paths(environ)
    environment.libpq_present(environ)
    location = environment.remote_location(environ)
    off_host_or_refused(location, environ)
    require_archiving_works(run=run)

    remote = Remote(location, prefix=environment.wal_prefix(environ), run=run)
    public_key = Path(environment.required(environment.PUBLIC_KEY_VAR, environ))
    staging = Path(environ.get("SYNCR_WAL_STAGING_DIR", WAL_STAGING_DIR))
    # Re-established on every run rather than once at deploy time: `archive_command` runs as the
    # Postgres user and a fresh volume belongs to root, so this is what makes the first archive of a
    # new deployment land at all.
    writable_by_postgres(staging, environ=environ)
    shipped = 0
    for segment in staged_segments(staging):
        _ship_one(segment, remote=remote, public_key=public_key, run=run)
        shipped += 1

    written = write_gauge(
        paths.textfile,
        family=WAL_METRIC,
        help_text="Unix time at which every WAL segment Postgres had archived was off-host.",
        value=now.timestamp(),
    )
    print(f"published {WAL_METRIC} to {written}")
    return shipped


def require_archiving_works(*, run: Run) -> None:
    """Refuse when Postgres's own archiver reports a failure it has not since recovered from.

    Read from the server rather than inferred from the directory. A failing ``archive_command``
    leaves the staging volume EMPTY, which is exactly what a healthy deployment leaves, so without
    this the gauge below would read fresh while nothing had been archived for a week.
    """
    stated = postgres.scalar(ARCHIVER_STATE, run=run)
    fields = stated.split("|")
    if len(fields) != 4:  # pragma: no cover - one row, four columns, or the server is not Postgres
        raise ArchivingFailing(f"pg_stat_archiver answered {stated!r}, which is not one row")
    archived, last_archived, failed, last_failed = fields
    if last_failed and (not last_archived or last_failed > last_archived):
        raise ArchivingFailing(
            f"Postgres last FAILED to archive at {last_failed} and last succeeded at "
            f"{last_archived or 'never'} ({failed} failures, {archived} archived). Segments are "
            "piling up in pg_wal and the recovery point is not being kept. Check the "
            "archive_command and the wal-archive volume; docs/runbooks/backup-stale.md is the "
            "procedure."
        )


def staged_segments(staging: Path) -> tuple[Path, ...]:
    """Every completed segment waiting to be shipped, oldest first.

    Sorted by name, which for WAL is LSN order and therefore replay order. A ``.history`` file and
    this module's own intermediates are excluded by suffix: shipping a partial file would put a
    segment in the bucket that recovery cannot read.
    """
    if not staging.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in staging.iterdir()
            if path.is_file() and not path.name.endswith(_NOT_A_SEGMENT)
        )
    )


def _ship_one(segment: Path, *, remote: Remote, public_key: Path, run: Run) -> None:
    """Compress, encrypt, upload, and only then remove the local segment."""
    compressed = Path(f"{segment}.gz")
    encrypted = Path(f"{compressed}{ENCRYPTED_SUFFIX}")
    try:
        run(["gzip", "--keep", "--force", "--best", str(segment)])
        crypto.encrypt(compressed, into=encrypted, public_key=public_key, run=run)
        remote.upload(encrypted, encrypted.name)
        segment.unlink(missing_ok=True)
    finally:
        compressed.unlink(missing_ok=True)
        encrypted.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
