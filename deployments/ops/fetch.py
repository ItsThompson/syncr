"""The newest backup, back out of the bucket and decrypted. ``python3 -m ops.fetch``.

Step one of the restore drill, and the step that proves the two things a drill exists to prove
before any database is involved:

- **The private key works.** It lives off the host and is brought here by a person for the drill. An
  encryption whose private half has never been used is a belief in the same way an untested backup
  is.
- **The object in the bucket is a restorable archive.** Verified here, from the copy that came back
  over the network, rather than from the staging file the dump step wrote and deleted.

The private key is imported into a throwaway ``GNUPGHOME`` under the scratch directory and never
into the deployment's own, so it exists for the length of one container.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ops import crypto, environment, naming, postgres, verify
from ops.fingerprint import read as read_fingerprint
from ops.prepare import writable_by_app
from ops.process import run as run_command
from ops.remote import Remote

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ops.process import Run

# What the restore and the comparison steps read, in the scratch volume all three mount.
FETCHED_DUMP = "restore.dump"
FETCHED_MANIFEST = "restore.manifest.json"

EXIT_OK = 0
EXIT_REFUSED = 1


class NothingToRestore(Exception):
    """The bucket holds no backup, which is the most important thing a drill can discover."""


def main() -> int:
    """Fetch and verify the newest backup. Returns the process exit status."""
    try:
        fetched = fetch(environ=os.environ, run=run_command)
    except Exception as refused:  # noqa: BLE001 - one message and a non-zero exit, whatever failed
        print(f"fetch refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"fetched {fetched}")
    return EXIT_OK


def fetch(*, environ: Mapping[str, str], run: Run) -> str:
    """Download, decrypt and verify the newest backup. Returns its name."""
    paths = environment.paths(environ)
    location = environment.remote_location(environ)
    remote = Remote(location, prefix=environment.dump_prefix(environ), run=run)
    private_key = Path(environment.required(environment.PRIVATE_KEY_VAR, environ))

    newest = newest_backup(remote)
    scratch = paths.scratch
    _clean(scratch)
    # The api image writes the restored copy's fingerprint into this same directory, and it does not
    # run as root: a directory this step created would otherwise be one that step cannot write to.
    writable_by_app(scratch, environ=environ)
    home = scratch / "gnupg"
    crypto.import_private_key(private_key, home=home, run=run)

    dump = scratch / FETCHED_DUMP
    manifest = scratch / FETCHED_MANIFEST
    _download_and_decrypt(remote, naming.dump_object(newest), into=dump, home=home, run=run)
    _download_and_decrypt(remote, naming.manifest_object(newest), into=manifest, home=home, run=run)

    reading = read_fingerprint(manifest)
    header = verify.read_header(dump)
    verify.require_tables(postgres.listing(dump, run=run), expected=reading.tables)
    print(
        f"the copy from {remote.location} is a usable archive: {header.version}, "
        f"{dump.stat().st_size} bytes, describing {reading.rows} rows over "
        f"{len(reading.tables)} tables taken at {reading.taken_at.isoformat()}"
    )
    return newest


def newest_backup(remote: Remote) -> str:
    """The most recent backup in the bucket, or a refusal saying the bucket is empty."""
    found = naming.backups_in(entry.name for entry in remote.listing())
    if not found:
        raise NothingToRestore(
            f"{remote.location} holds no backup this deployment recognises. If the nightly job has "
            "never succeeded, there is nothing to drill and BackupStale is telling the truth."
        )
    return found[0]


def _download_and_decrypt(
    remote: Remote, object_name: str, *, into: Path, home: Path, run: Run
) -> None:
    encrypted = into.with_name(f"{into.name}.gpg")
    try:
        remote.download(object_name, encrypted)
        crypto.decrypt(encrypted, into=into, home=home, run=run)
    finally:
        encrypted.unlink(missing_ok=True)


def _clean(scratch: Path) -> None:
    """Empty the scratch directory, so nothing an earlier drill left can satisfy this one.

    Its CONTENTS, not the directory: it is a volume mount point, and removing one fails with
    ``Device or resource busy``. Measured by running the drill, which is the only way that shape
    shows up.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    for path in scratch.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


if __name__ == "__main__":
    sys.exit(main())
