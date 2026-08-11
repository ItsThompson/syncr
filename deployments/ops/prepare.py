"""The volumes this path writes to, owned by the users that write to them.

A FRESH NAMED VOLUME IS ROOT-OWNED, and two of the three containers that write into these are not
root: the api image runs as ``syncr`` and Postgres runs as ``postgres``. So the first write into a
new volume fails with a permission error, and which container created the volume decides whose it
is, which makes the failure depend on the order the steps happened to run in.

This step removes the order from the question. It runs in the ops image, which IS root, and it is
the first thing ``just backup-now`` does. Idempotent, so every run re-establishes the property
rather than assuming an earlier one did.

**The two user ids are stated in Compose, not guessed here.** ``just uid-check`` crosses them
against what the images actually run as, so a base image that renumbers its user fails a check
rather than a backup.

Modes are 0750: the staging directory holds a plaintext dump for as long as it takes to encrypt it,
and the WAL staging directory holds complete transaction records. Neither is world-readable, and
neither is a staged segment waiting for a recovery to copy it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ops import environment
from ops.config import WAL_STAGING_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping

# Which user each directory's writer runs as. Read from the environment because it is a property of
# the images, and stated in `docker-compose.yml` beside the volumes themselves.
APP_UID_VAR: Final = "SYNCR_APP_UID"
POSTGRES_UID_VAR: Final = "SYNCR_POSTGRES_UID"

DIRECTORY_MODE: Final = 0o750

# One staged file's mode. Group-readable rather than 0600, because the process that writes a WAL
# segment into the recovery volume and the process that copies it out are different users; not
# world-readable, for the reason the directory modes are not.
FILE_MODE: Final = 0o640

EXIT_OK = 0
EXIT_REFUSED = 1


def main() -> int:
    """Prepare every volume the backup path writes into. Returns the process exit status."""
    try:
        prepared = prepare(environ=os.environ)
    except Exception as refused:  # noqa: BLE001 - one message and a non-zero exit, whatever failed
        print(f"preparing the volumes refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    for path in prepared:
        print(f"prepared {path}")
    return EXIT_OK


def prepare(*, environ: Mapping[str, str]) -> tuple[Path, ...]:
    """Establish ownership on the three directories, and say which were touched."""
    paths = environment.paths(environ)
    staging = Path(environ.get("SYNCR_WAL_STAGING_DIR", WAL_STAGING_DIR))
    writable_by_app(paths.staging, environ=environ)
    writable_by_app(paths.scratch, environ=environ)
    writable_by_postgres(staging, environ=environ)
    return (paths.staging, paths.scratch, staging)


def writable_by_app(path: Path, *, environ: Mapping[str, str]) -> None:
    """Make one directory writable by the user the application images run as.

    The api image writes two files into volumes: the fingerprint the dump uploads beside the
    archive, and the reading taken against a restored copy.
    """
    _owned(path, uid=int(environ.get(APP_UID_VAR, "999")))


def writable_by_postgres(path: Path, *, environ: Mapping[str, str]) -> None:
    """Make one directory writable by the user Postgres runs as.

    ``archive_command`` runs inside the database container as that user. A directory it cannot write
    to means Postgres retries the same segment forever, which `pg_stat_archiver` reports and
    ``ops.ship`` refuses on.
    """
    _owned(path, uid=_postgres_uid(environ))


def readable_by_postgres(path: Path, *, environ: Mapping[str, str]) -> None:
    """Give one FILE to the user Postgres runs as, so ``restore_command`` can copy it.

    gpg and gzip write 0600 as the user running them, which in the ops image is root, and
    ``restore_command`` runs as the database's own user in another container. Without this the file
    is there and unreadable, which Postgres reports as a failed restore command and a recovery reads
    as the end of the archive.
    """
    _given_to(path, uid=_postgres_uid(environ), mode=FILE_MODE)


def _postgres_uid(environ: Mapping[str, str]) -> int:
    return int(environ.get(POSTGRES_UID_VAR, "999"))


def _owned(path: Path, *, uid: int) -> None:
    """Create the directory if it is absent, and give it to ``uid``."""
    path.mkdir(parents=True, exist_ok=True)
    _given_to(path, uid=uid, mode=DIRECTORY_MODE)


def _given_to(path: Path, *, uid: int, mode: int) -> None:
    """Set one path's mode, and its owner where this process is allowed to.

    ``os.chown`` needs root, which the ops image is and the others are not. A run as a non-root user
    leaves the ownership alone rather than failing: in a test there is nothing to establish.
    """
    path.chmod(mode)
    if os.geteuid() == 0:
        os.chown(path, uid, uid)


if __name__ == "__main__":
    sys.exit(main())
