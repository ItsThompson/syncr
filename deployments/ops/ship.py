"""WAL segments to the same bucket, once a minute. ``python3 -m ops.ship``.

Postgres's ``archive_command`` copies a completed segment into a staging volume; this compresses it,
encrypts it, uploads it, and removes the local copy. The recovery point is therefore bounded by
``archive_timeout`` plus this interval, which is the arithmetic ``ops.config`` states.

**The freshness gauge is written only when Postgres itself says archiving is working.** Draining an
empty staging directory looks identical to a healthy deployment and to one whose ``archive_command``
has been failing for a week: in the second case the segments never reach the volume at all, and a
shipper that published a fresh timestamp for an empty directory would report a five-minute recovery
point while none existed. ``pg_stat_archiver`` is the server's own record of that, so it is read
first, and a pending failure refuses.

**And so does archiving being switched OFF, which is the same hole reached the other way.** Measured
by a reviewer: a server with ``archive_mode = off`` reports zero archived, zero failed and no
timestamps, so a guard over failures alone passes and the gauge is published fresh. The set that
guard could see was narrower than the set it claimed to bound. So the reading takes the SETTINGS
too: ``archive_mode`` must be archiving and ``wal_level`` at least ``replica``, which is what
makes a segment exist to archive at all.

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

from ops import crypto, environment, naming, postgres
from ops.config import COMPRESSED_SUFFIX, ENCRYPTED_SUFFIX, WAL_METRIC, WAL_STAGING_DIR
from ops.exposition import write_gauge
from ops.prepare import writable_by_postgres
from ops.process import run as run_command
from ops.remote import Remote, off_host_or_refused

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ops.process import Run

EXIT_OK = 0
EXIT_REFUSED = 1

# `pg_stat_archiver` and the two settings that decide whether it can ever move, in one row.
#
# THE PENDING-FAILURE COMPARISON IS SQL'S, not this module's: comparing two `timestamptz::text`
# values lexically matches time order only while the UTC offset is constant, and a server whose zone
# changed would invert it. Postgres knows how to compare its own timestamps.
ARCHIVER_STATE = (
    "SELECT current_setting('archive_mode'), current_setting('wal_level'), "
    "archived_count, failed_count, "
    "(last_failed_time IS NOT NULL AND (last_archived_time IS NULL "
    "OR last_failed_time > last_archived_time)) AS pending, "
    "coalesce(last_archived_time::text, ''), coalesce(last_failed_time::text, '') "
    "FROM pg_stat_archiver"
)

# What `archive_mode` must be for a segment to reach the staging volume at all, and the floor
# `wal_level` has to clear for one to be replayable. `always` also archives, on a standby.
_ARCHIVING_ON = frozenset({"on", "always"})
_REPLAYABLE_WAL = frozenset({"replica", "logical"})

# How many fields the reading above returns. Asserted, because a short row means the server answered
# something other than one row of seven and every field below would be read off by one.
_ARCHIVER_FIELDS = 7

# What the compressor leaves behind while it works, and what a previous run may have left. Neither
# is a segment to ship.
#
# `.history` IS NOT EXCLUDED, and that is a correction: a timeline history file is what a
# point-in-time recovery reads to follow a timeline switch, `archive_command` copies it into the
# staging volume like anything else, and excluding it both left it out of the bucket and left it on
# the volume forever. It is a few hundred bytes and it ships like a segment.
_NOT_A_SEGMENT = (COMPRESSED_SUFFIX, ENCRYPTED_SUFFIX, ".tmp", ".partial")


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
    # `shipped` on the line, so `journalctl -u syncr-walship.service` tells "nothing to ship" from
    # "shipping": on a quiet database zero is the correct and expected figure, and a reader of
    # BackupStale will otherwise assume the series moving means WAL is moving.
    print(f"published {WAL_METRIC} to {written}, having shipped {shipped}")
    return shipped


def require_archiving_works(*, run: Run) -> None:
    """Refuse unless Postgres is archiving AND has not failed since it last succeeded.

    Read from the server rather than inferred from the directory, and TWO readings rather than one.
    A failing ``archive_command`` leaves the staging volume EMPTY, which is exactly what a healthy
    deployment leaves; and archiving switched OFF leaves it empty with no failures to find. Without
    both, the gauge below reads fresh while nothing has been archived at all.
    """
    stated = postgres.scalar(ARCHIVER_STATE, run=run)
    fields = stated.split("|")
    if len(fields) != _ARCHIVER_FIELDS:
        raise ArchivingFailing(
            f"pg_stat_archiver answered {stated!r}, which is not one row of "
            f"{_ARCHIVER_FIELDS} fields"
        )
    mode, level, archived, failed, pending, last_archived, last_failed = fields
    if mode not in _ARCHIVING_ON:
        raise ArchivingFailing(
            f"this server has archive_mode = {mode!r}, so NOTHING is being archived and the "
            "staging volume is empty for that reason rather than because it was drained. The "
            "recovery point does not exist. `docker-compose.yml` sets archive_mode on, so check "
            "which stack this is pointed at before changing anything."
        )
    if level not in _REPLAYABLE_WAL:
        raise ArchivingFailing(
            f"this server has wal_level = {level!r}, which does not produce WAL a recovery can "
            "replay. `docker-compose.yml` sets replica."
        )
    if pending == "t":
        raise ArchivingFailing(
            f"Postgres last FAILED to archive at {last_failed} and last succeeded at "
            f"{last_archived or 'never'} ({failed} failures, {archived} archived). Segments are "
            "piling up in pg_wal and the recovery point is not being kept. Check the "
            "archive_command and the wal-archive volume; docs/runbooks/backup-stale.md is the "
            "procedure."
        )


def staged_segments(staging: Path) -> tuple[Path, ...]:
    """Every completed file waiting to be shipped, oldest first.

    Sorted by name, which for WAL is LSN order and therefore replay order. This module's own
    intermediates are excluded by suffix: shipping a partial file would put an object in the bucket
    that recovery cannot read. A `.history` file is NOT excluded: see the constant.
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
    compressed = Path(f"{segment}{COMPRESSED_SUFFIX}")
    encrypted = Path(f"{compressed}{ENCRYPTED_SUFFIX}")
    try:
        run(["gzip", "--keep", "--force", "--best", str(segment)])
        crypto.encrypt(compressed, into=encrypted, public_key=public_key, run=run)
        remote.upload(encrypted, naming.segment_object(segment.name))
        segment.unlink(missing_ok=True)
    finally:
        compressed.unlink(missing_ok=True)
        encrypted.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
