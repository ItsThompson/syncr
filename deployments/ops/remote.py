"""The off-host bucket, through rclone, and the refusal that makes "off-host" mean something.

**A backup on the same disk as the database is not a backup.** That sentence is in the spec twice
and it is the only rule in this module that is not a wrapper: :func:`off_host_or_refused` reads the
SAME configuration rclone will resolve the remote from, so a deployment whose bucket is a directory
on the VPS fails at the top of the nightly run instead of accumulating copies that die with the
disk.

Credentials never appear here. rclone reads a remote from ``RCLONE_CONFIG_<NAME>_*`` environment
variables, which is what the host secret file injects, so there is no configuration file to write
and nothing to leave behind in an image.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ops.process import CommandFailed

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from ops.process import Result, Run

# The environment variable naming a remote's type, as rclone spells it.
_TYPE_TEMPLATE = "RCLONE_CONFIG_{name}_TYPE"

# The escape hatch, for the restore drill and for a developer looking at the path locally. Named
# rather than inferred: a deployment that sets this has said in writing that its bucket is not
# off-host.
ALLOW_LOCAL = "SYNCR_BACKUP_ALLOW_LOCAL_REMOTE"

# rclone's exit status for "the directory does not exist", which is a legitimate reading rather than
# a failure: on the first night the WAL prefix holds no objects, so the prefix itself does not exist
# yet. Any other non-zero status is a failure and is raised.
_DIRECTORY_NOT_FOUND = 3

_LOCAL_TYPES = frozenset({"local", "alias"})


class NotOffHost(Exception):
    """The configured remote is a directory on this host, so copies to it are not backups."""


def off_host_or_refused(remote: str, environ: Mapping[str, str]) -> None:
    """Refuse a remote that is this machine's own filesystem.

    Two shapes are refused. A remote with no ``:`` is a path, and rclone would copy to it happily. A
    remote whose configured type is ``local`` or ``alias`` is a path with a name.
    """
    if environ.get(ALLOW_LOCAL) == "1":
        return
    name, separator, _ = remote.partition(":")
    if not separator:
        raise NotOffHost(
            f"{remote!r} names no remote, so it is a path on this host. A backup on the same disk "
            f"as the database is not a backup. Set {ALLOW_LOCAL}=1 only for a drill."
        )
    declared = environ.get(_TYPE_TEMPLATE.format(name=name.upper()), "")
    if declared in _LOCAL_TYPES:
        raise NotOffHost(
            f"remote {name!r} is configured as type {declared!r}, which is this host's own "
            f"filesystem. A backup on the same disk as the database is not a backup. Set "
            f"{ALLOW_LOCAL}=1 only for a drill."
        )


@dataclass(frozen=True, slots=True)
class Entry:
    """One object in the bucket, as a listing reports it."""

    name: str
    size: int
    modified_at: datetime


class Remote:
    """One prefix of one rclone remote: upload, list, download, delete.

    Deliberately four narrow methods rather than a general "run rclone" seam. Each one is what a
    caller means, and each is mockable with a single return shape.
    """

    def __init__(self, remote: str, *, prefix: str, run: Run, rclone: str = "rclone") -> None:
        self._remote = remote.rstrip("/")
        self._prefix = prefix.strip("/")
        self._run = run
        self._rclone = rclone

    @property
    def location(self) -> str:
        """The remote path this instance reads and writes, as rclone spells it."""
        return f"{self._remote}/{self._prefix}" if self._prefix else self._remote

    def upload(self, local: Path, object_name: str) -> None:
        """Copy one local file to one object name.

        ``copyto`` rather than ``copy``, because ``copy`` takes a directory as its destination and
        would silently create ``<prefix>/<object>/<filename>`` on a caller that passed a name.
        """
        self._rclone_call(["copyto", str(local), f"{self.location}/{object_name}"])

    def download(self, object_name: str, local: Path) -> None:
        """Copy one object to one local path."""
        self._rclone_call(["copyto", f"{self.location}/{object_name}", str(local)])

    def delete(self, object_name: str) -> None:
        """Remove one object."""
        self._rclone_call(["deletefile", f"{self.location}/{object_name}"])

    def listing(self) -> tuple[Entry, ...]:
        """Every object under the prefix, with its size and modification time.

        ``lsjson`` rather than ``ls``, because the modification time is what WAL retention is
        decided from: a segment's name is an LSN and carries no clock at all.

        **A prefix that does not exist reads as empty rather than as a failure.** rclone exits 3 for
        it, and it is the correct state on a deployment whose shipper has not run yet. That reading
        is safe here because nothing downstream deletes on the strength of an empty listing:
        retention refuses outright unless the backup this run just uploaded is in it.
        """
        result = self._run([self._rclone, "lsjson", self.location], check=False)
        if result.returncode == _DIRECTORY_NOT_FOUND:
            return ()
        if result.returncode != 0:
            raise CommandFailed(f"rclone could not list {self.location}: {result.stderr.strip()}")
        parsed = json.loads(result.stdout or "[]")
        return tuple(
            Entry(
                name=str(item["Name"]),
                size=int(item["Size"]),
                modified_at=_parsed_time(str(item["ModTime"])),
            )
            for item in parsed
            if not item.get("IsDir", False)
        )

    def _rclone_call(self, arguments: Sequence[str]) -> Result:
        return self._run([self._rclone, *arguments])


def _parsed_time(stated: str) -> datetime:
    """rclone's RFC 3339 timestamp, whose nanosecond precision Python 3.11 cannot read."""
    normalised = stated.replace("Z", "+00:00")
    head, _, tail = normalised.partition(".")
    if tail:
        fraction, sign, offset = tail.partition("+")
        normalised = f"{head}.{fraction[:6]}{sign}{offset}"
    return datetime.fromisoformat(normalised)
