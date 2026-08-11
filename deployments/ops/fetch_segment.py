"""One archived WAL segment, out of the bucket and into the volume a recovery copies from.

``python3 -m ops.fetch_segment 000000010000000000000003``

**The database container makes no network call and holds no key.** That is the rule
``archive_command`` keeps on the way out -- it copies a completed segment into a volume and a
one-shot ships it -- and this is the same rule on the way back: this step fetches and decrypts, and
``restore_command`` copies from the volume and does nothing else.
``docker-compose.restore.yml`` states the choice where that command lives.

ONE SEGMENT PER INVOCATION, and the exit status is the answer about that one name:

===  =========================================================================================
  0  staged, complete, and owned by the user that copies it out
  1  refused, with the reason on stderr
  2  the bucket holds no such object, which is how a recovery finds the end of the archive
===  =========================================================================================

A recovery asks for the next segment until one is missing, so "not there" is an ordinary answer and
has an exit status of its own. A caller that could not tell it from a broken bucket would stop
replaying either way and call the result a recovery.

The staging directory is inside the scratch volume, which ``ops.fetch`` empties at the start of a
drill. That is what keeps a segment an earlier run staged from satisfying a later one, and it means
a segment staged BEFORE the dump is fetched is gone: stage after that step, never before.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ops import environment, naming
from ops.config import COMPRESSED_SUFFIX, WAL_STAGING_DIR
from ops.crypto import import_private_key
from ops.fetch import GNUPG_HOME, download_and_decrypt
from ops.prepare import readable_by_postgres, writable_by_postgres
from ops.process import run as run_command
from ops.remote import Remote

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ops.environment import Paths
    from ops.process import Run

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_ABSENT = 2

# WHAT POSTGRES ITSELF ASKS `restore_command` FOR, and nothing else: a segment, the label a base
# backup leaves behind, or a timeline history file. Upper-case hex because that is what Postgres
# writes.
#
# `fullmatch` RATHER THAN AN ANCHORED PATTERN, and the difference is measured rather than stylistic.
# `re.match` anchors the start on its own, and `$` matches BEFORE a single trailing newline: a name
# ending in one was admitted with a span 24 characters long out of 25, staged under a name with the
# newline in it, and reported staged. `restore_command` can never ask for that name, and a segment
# Postgres cannot ask for is a segment it treats as the end of the archive.
SEGMENT_NAME: Final = re.compile(r"(?:[0-9A-F]{24}(?:\.[0-9A-F]{8}\.backup)?|[0-9A-F]{8}\.history)")

# What an incomplete segment is called while it is being fetched. Postgres never asks for a name
# ending in this, so a file under it is invisible to `restore_command` however far it got.
WORKING_SUFFIX: Final = ".part"


class SegmentRefused(Exception):
    """The staging step stopped before it wrote anything."""


class SegmentAbsent(Exception):
    """The bucket holds no such object, which for a recovery is the end of the archive."""


def main() -> int:
    """Stage the one segment this invocation names. Returns the process exit status."""
    try:
        staged = fetch_segment(requested_segment(sys.argv[1:]), environ=os.environ, run=run_command)
    except SegmentAbsent as absent:
        print(f"nothing to stage: {absent}", file=sys.stderr)
        return EXIT_ABSENT
    except Exception as refused:  # noqa: BLE001 - one message and a non-zero exit, whatever failed
        print(f"staging a segment refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"staged {staged}")
    return EXIT_OK


def requested_segment(arguments: Sequence[str]) -> str:
    """The one segment name an invocation carries, or a refusal saying why it is not one."""
    if len(arguments) != 1:
        raise SegmentRefused(
            f"this step stages ONE segment per invocation and was given {len(arguments)} "
            "arguments. A recovery asks for one name at a time, and this step's exit status is the "
            "answer about that one name."
        )
    segment = arguments[0]
    if SEGMENT_NAME.fullmatch(segment) is None:
        raise SegmentRefused(
            f"{segment!r} is not a name Postgres asks a restore command for. Those are 24 "
            "upper-case hex digits, that followed by `.<8 hex>.backup`, or 8 hex digits followed "
            "by `.history`. Nothing else is joined to the staging path."
        )
    return segment


def fetch_segment(segment: str, *, environ: Mapping[str, str], run: Run) -> Path:
    """Stage one decrypted segment where the recovery reads it. Returns the file written."""
    paths = environment.paths(environ)
    into = paths.wal_restore
    require_a_directory_of_its_own(into, paths=paths, environ=environ)
    private_key = Path(environment.required(environment.PRIVATE_KEY_VAR, environ))
    remote = Remote(
        environment.remote_location(environ), prefix=environment.wal_prefix(environ), run=run
    )
    object_name = naming.segment_object(segment)
    require_in_the_bucket(remote, object_name)

    writable_by_postgres(into, environ=environ)
    home = paths.scratch / GNUPG_HOME
    import_private_key(private_key, home=home, run=run)
    staged = into / segment
    working = into / f"{segment}{WORKING_SUFFIX}"
    compressed = working.with_name(f"{working.name}{COMPRESSED_SUFFIX}")
    try:
        download_and_decrypt(remote, object_name, into=compressed, home=home, run=run)
        # `gzip --decompress` writes the name with the suffix stripped, which is the working name,
        # and the complete file is then MOVED under the name Postgres asks for. A partial file under
        # that name is one `restore_command` would copy and Postgres would try to replay.
        run(["gzip", "--decompress", "--force", str(compressed)])
        working.replace(staged)
    finally:
        compressed.unlink(missing_ok=True)
        working.unlink(missing_ok=True)
    readable_by_postgres(staged, environ=environ)
    print(f"{object_name} from {remote.location} is {staged.stat().st_size} bytes decompressed")
    return staged


def require_a_directory_of_its_own(into: Path, *, paths: Paths, environ: Mapping[str, str]) -> None:
    """Refuse to stage into a directory another step of this path already owns.

    This step creates the directory it stages into and gives it to the user Postgres runs as, so
    pointing it at one of the others would re-own that directory as a side effect. The WAL staging
    volume is worse than that: ``ops.ship`` uploads and then DELETES every file it finds there, so a
    segment staged in it would be shipped back to the bucket and removed before a recovery could
    copy it.
    """
    live_wal_staging = Path(environ.get("SYNCR_WAL_STAGING_DIR", WAL_STAGING_DIR))
    occupied = {
        live_wal_staging.resolve(): (
            "the volume `archive_command` writes into, which the shipper drains by uploading every "
            "file in it and then removing it"
        ),
        paths.staging.resolve(): "the dump's staging volume",
        paths.scratch.resolve(): "the scratch volume's own root, which the dump is fetched into",
        paths.textfile.resolve(): "the metrics textfile collector",
    }
    reason = occupied.get(into.resolve())
    if reason is not None:
        raise SegmentRefused(
            f"{into} is {reason}. A segment is staged in a directory of its own, whose only reader "
            "is the recovery instance's restore command."
        )


def require_in_the_bucket(remote: Remote, object_name: str) -> None:
    """Refuse a name the bucket does not hold, distinctly from a fetch that failed.

    The listing rather than the download's own failure, because those two answers mean opposite
    things: an object that is not there ends a recovery correctly, and a bucket that cannot be read
    ends it at a point nobody chose.
    """
    held = {entry.name for entry in remote.listing()}
    if object_name not in held:
        raise SegmentAbsent(
            f"{remote.location} holds no {object_name}, among {len(held)} objects. If a recovery "
            "asked for this name, the archive ends before it; if a person did, the name is not one "
            "this deployment ever archived."
        )


if __name__ == "__main__":
    sys.exit(main())
