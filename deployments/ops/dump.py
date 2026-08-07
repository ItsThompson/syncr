"""The nightly backup, end to end, inside the ops image. ``python3 -m ops.dump``.

Runs at 03:00 host time, after ``syncr-plan-fingerprint`` has written the reading a restore will be
checked against. That order is enforced here rather than assumed: the fingerprint must exist and be
recent, or this refuses. An old fingerprint uploaded beside a new dump describes another day's data,
and the drill it feeds would compare two unrelated readings and pass.

**The metric ``BackupStale`` reads is written LAST and only on success.** That is what makes the
alert mean what it says: a run that refused anywhere above leaves the timestamp where it was, and
the alert fires 36 hours later.

**The plaintext dump is deleted whatever happens, and the encrypted copy once it is in the bucket.**
The plaintext holds every block title and every anchor location, so it exists for as long as it
takes to encrypt it. The encrypted one goes because a copy on this host is not a backup, and the
disk it would fill is the one Postgres writes to.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ops import crypto, environment, naming, postgres, retention, verify
from ops.config import BACKUP_METRIC, DUMP_SUFFIX, ENCRYPTED_SUFFIX, MANIFEST_MAX_AGE_SECONDS
from ops.exposition import write_gauge
from ops.fingerprint import Fingerprint
from ops.fingerprint import read as read_fingerprint
from ops.process import run as run_command
from ops.remote import Remote, off_host_or_refused

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ops.process import Run

# What `syncr-plan-fingerprint` is pointed at, in the volume both containers mount.
FINGERPRINT_FILE = "fingerprint.json"

EXIT_OK = 0
EXIT_REFUSED = 1

_STILL_READS = (
    "the completion timestamp is NOT written, so BackupStale still reads the last run that "
    "succeeded. docs/runbooks/backup-stale.md is the procedure."
)


class BackupRefused(Exception):
    """The run stopped before it could produce something misleading."""


def main() -> int:
    """Take one backup. Returns the process exit status."""
    try:
        taken = take_backup(environ=os.environ, run=run_command)
    except Exception as refused:  # noqa: BLE001 - one message and a non-zero exit, whatever failed
        print(f"backup refused: {refused}", file=sys.stderr)
        print(_STILL_READS, file=sys.stderr)
        return EXIT_REFUSED
    print(f"backup {taken} complete")
    return EXIT_OK


def take_backup(*, environ: Mapping[str, str], run: Run) -> str:
    """Dump, verify, encrypt, upload, prune, publish. Returns the backup's name."""
    now = datetime.now(tz=UTC)
    name = naming.stamp(now)
    paths = environment.paths(environ)
    target = environment.libpq_present(environ)
    location = environment.remote_location(environ)
    off_host_or_refused(location, environ)
    remote = Remote(location, prefix=environment.dump_prefix(environ), run=run)

    reading = paths.staging / FINGERPRINT_FILE
    manifest = recent_fingerprint(reading, now=now)
    print(f"dumping {target}: {manifest.rows} rows over {len(manifest.tables)} tables")

    archive = paths.staging / f"{name}{DUMP_SUFFIX}"
    try:
        postgres.dump(archive, run=run)
        header = verify.read_header(archive)
        verify.require_tables(postgres.listing(archive, run=run), expected=manifest.tables)
        print(f"verified: archive {header.version}, {archive.stat().st_size} bytes")
        _upload(archive, reading=reading, name=name, environ=environ, remote=remote, run=run)
    finally:
        archive.unlink(missing_ok=True)

    _prune(remote, just_uploaded=name, location=location, run=run, environ=environ)
    written = write_gauge(
        paths.textfile,
        family=BACKUP_METRIC,
        help_text="Unix time of the last successful off-host backup.",
        value=now.timestamp(),
    )
    print(f"published {BACKUP_METRIC} to {written}")
    return name


def recent_fingerprint(path: Path, *, now: datetime) -> Fingerprint:
    """The reading the restore will be checked against, or a refusal.

    Its AGE is the check that matters. ``syncr-plan-fingerprint`` runs immediately before this in
    the same recipe, so a file older than the window means that step failed and left an earlier one
    behind.
    """
    if not path.is_file():
        raise BackupRefused(
            f"{path} does not exist, so no reading of the live database was taken. "
            "`just backup-now` "
            "runs `syncr-plan-fingerprint` first, in order."
        )
    age = now.timestamp() - path.stat().st_mtime
    if age > MANIFEST_MAX_AGE_SECONDS:
        raise BackupRefused(
            f"{path} is {age:.0f}s old, past the {MANIFEST_MAX_AGE_SECONDS}s window. It describes "
            "an earlier state, so a drill comparing it against this dump would compare two "
            "different days and pass."
        )
    return read_fingerprint(path)


def _upload(
    archive: Path,
    *,
    reading: Path,
    name: str,
    environ: Mapping[str, str],
    remote: Remote,
    run: Run,
) -> None:
    """Encrypt both files to the off-host recipient and put them in the bucket."""
    public_key = Path(environment.required(environment.PUBLIC_KEY_VAR, environ))
    encrypted_dump = Path(f"{archive}{ENCRYPTED_SUFFIX}")
    encrypted_reading = Path(f"{reading}{ENCRYPTED_SUFFIX}")
    try:
        crypto.encrypt(archive, into=encrypted_dump, public_key=public_key, run=run)
        crypto.encrypt(reading, into=encrypted_reading, public_key=public_key, run=run)
        remote.upload(encrypted_dump, naming.dump_object(name))
        remote.upload(encrypted_reading, naming.manifest_object(name))
        print(f"uploaded {naming.dump_object(name)} and its fingerprint to {remote.location}")
    finally:
        encrypted_dump.unlink(missing_ok=True)
        encrypted_reading.unlink(missing_ok=True)


def _prune(
    remote: Remote,
    *,
    just_uploaded: str,
    location: str,
    run: Run,
    environ: Mapping[str, str],
) -> None:
    """Apply retention to the dumps, then to the WAL a retained dump could be replayed onto."""
    present = [entry.name for entry in remote.listing()]
    plan = retention.plan(present, just_uploaded=just_uploaded)
    for object_name in retention.objects_to_delete(present, plan.delete):
        remote.delete(object_name)
    unrecognised = (
        f"; {len(plan.unclassified)} objects were not recognised and were kept"
        if plan.unclassified
        else ""
    )
    print(f"retention keeps {len(plan.keep)} backups, deleted {len(plan.delete)}{unrecognised}")
    _prune_wal(location, oldest_kept=plan.keep[-1], run=run, environ=environ)


def _prune_wal(location: str, *, oldest_kept: str, run: Run, environ: Mapping[str, str]) -> None:
    """Delete WAL that no retained dump could be replayed onto."""
    oldest = naming.taken_at(oldest_kept)
    if oldest is None:  # pragma: no cover - a plan keeps only names carrying a stamp
        return
    wal = Remote(location, prefix=environment.wal_prefix(environ), run=run)
    segments = [(entry.name, entry.modified_at) for entry in wal.listing()]
    stale = retention.wal_to_delete(segments, oldest_kept_backup=oldest)
    for object_name in stale:
        wal.delete(object_name)
    print(f"WAL retention keeps {len(segments) - len(stale)} segments, deleted {len(stale)}")


if __name__ == "__main__":
    sys.exit(main())
