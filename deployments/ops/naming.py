"""What a backup object is called, and how the instant it was taken is read back out of the name.

The name carries the instant because retention is decided from the listing alone: reading a
timestamp out of seventeen object names costs one listing, and reading it out of seventeen encrypted
dumps would cost seventeen downloads and the private key, which is held off the host on purpose.

UTC, always, and stated in the name as ``Z``. The schedule is host-local (03:00) and the name is
not, because a host that changes zone or crosses a daylight-saving boundary would otherwise produce
two objects claiming the same hour, and retention sorts on this string.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from ops.config import DUMP_SUFFIX, ENCRYPTED_SUFFIX, MANIFEST_SUFFIX

if TYPE_CHECKING:
    from collections.abc import Iterable

# `syncr-20260807T030000Z`, and nothing else this path writes looks like it.
_STAMP_FORMAT: Final = "%Y%m%dT%H%M%SZ"
_PREFIX: Final = "syncr-"
_STAMP = re.compile(rf"{_PREFIX}(\d{{8}}T\d{{6}}Z)")


def stamp(when: datetime) -> str:
    """The name fragment identifying one backup, from the instant it was taken."""
    return _PREFIX + when.astimezone(UTC).strftime(_STAMP_FORMAT)


def dump_object(name: str) -> str:
    """The encrypted dump's object name for this backup."""
    return f"{name}{DUMP_SUFFIX}{ENCRYPTED_SUFFIX}"


def manifest_object(name: str) -> str:
    """The encrypted fingerprint's object name for this backup."""
    return f"{name}{MANIFEST_SUFFIX}{ENCRYPTED_SUFFIX}"


def objects_for(name: str) -> tuple[str, ...]:
    """Every object one backup consists of.

    The pair travels together in both directions: a dump whose fingerprint was deleted cannot be
    checked after a restore, and a fingerprint whose dump was deleted describes nothing.
    """
    return (dump_object(name), manifest_object(name))


def taken_at(object_name: str) -> datetime | None:
    """When the backup this object belongs to was taken, or ``None`` when the name does not say.

    ``None`` is not an error and it is not a licence to delete: retention keeps what it cannot
    classify and reports it, because an object nobody here recognises is more likely to be someone
    else's deliberate copy than to be garbage.
    """
    found = _STAMP.search(object_name)
    if found is None:
        return None
    try:
        # The stamp this module wrote is UTC by construction and carries `Z` rather than an offset
        # `%z` could read, so the zone is attached below rather than parsed.
        parsed = datetime.strptime(found.group(1), _STAMP_FORMAT)  # noqa: DTZ007
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def backups_in(object_names: Iterable[str]) -> tuple[str, ...]:
    """Every distinct backup name a listing holds, newest first.

    One backup is two objects, so the listing is collapsed onto the name they share before anything
    counts copies. Sorted by the stamp, which sorts lexically because it is fixed-width UTC.
    """
    found = {
        f"{_PREFIX}{match.group(1)}"
        for name in object_names
        if (match := _STAMP.search(name)) is not None
    }
    return tuple(sorted(found, reverse=True))
