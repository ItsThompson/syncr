"""Which copies a listing keeps and which it deletes: 7 daily, 4 weekly, 6 monthly.

The rule this module exists for is not the arithmetic, which is three counts. It is that **retention
is the one step in the backup path that destroys data**, so every refusal below is a case where the
honest answer is to delete nothing:

- **The listing does not hold the backup this run just uploaded.** The listing is of the wrong
  bucket or prefix, and every name in it belongs to something else.
- **A plan would delete the newest backup.** Retention deleting the only current copy is the one
  shape that turns a working backup path into no backup at all.
- **An object whose name carries no timestamp.** Someone else's deliberate copy, or a partial
  upload. Kept, and reported.

The classes overlap deliberately. A Monday dump is a daily AND a weekly, and one taken on the first
of a month that falls on a Monday is all three, so the sets are unioned rather than partitioned: a
copy is kept when ANY class still wants it. Partitioning would make the retained history depend on
which class claimed a copy first, which is not a property anyone should have to reason about while
deciding whether last month's data still exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ops.config import (
    DAILY_COPIES,
    MONTHLY_COPIES,
    MONTHLY_ON_DAY,
    WAL_RETENTION_MARGIN_SECONDS,
    WEEKLY_COPIES,
    WEEKLY_ON_WEEKDAY,
)
from ops.naming import backups_in, objects_for, taken_at

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime


class RetentionRefused(Exception):
    """Retention declined to delete anything, because the listing it read cannot be trusted."""


@dataclass(frozen=True, slots=True)
class Plan:
    """What to keep, what to delete, and what this module did not recognise."""

    keep: tuple[str, ...]
    delete: tuple[str, ...]
    unclassified: tuple[str, ...]


def plan(object_names: Sequence[str], *, just_uploaded: str) -> Plan:
    """Decide retention over one listing, or refuse.

    ``just_uploaded`` is the backup the calling run wrote a moment ago. Requiring it to be present
    is what makes this a decision about the right bucket: an empty listing, a mistyped prefix, and a
    remote pointing at a different deployment all produce a listing that looks prunable and holds
    nobody's copies.
    """
    backups = backups_in(object_names)
    unclassified = tuple(sorted(name for name in object_names if taken_at(name) is None))
    if just_uploaded not in backups:
        raise RetentionRefused(
            f"{just_uploaded} is not in a listing of {len(backups)} backups, so this listing is "
            "not of the location this run uploaded to. Nothing deleted."
        )

    keep = _kept(backups)
    delete = tuple(name for name in backups if name not in keep)
    if backups[0] in delete or just_uploaded in delete:
        raise RetentionRefused(
            f"retention would delete {backups[0]}, the newest copy there is. Nothing deleted."
        )
    return Plan(keep=tuple(sorted(keep, reverse=True)), delete=delete, unclassified=unclassified)


def objects_to_delete(present: Iterable[str], deleting: Iterable[str]) -> tuple[str, ...]:
    """The object names to remove, for the backups a plan deletes.

    Both objects of a backup go together. Only names the listing actually held are returned, so a
    backup whose fingerprint upload failed does not produce a delete for an object that never
    existed.
    """
    held = set(present)
    return tuple(
        sorted(name for backup in deleting for name in objects_for(backup) if name in held)
    )


def _kept(backups: Sequence[str]) -> set[str]:
    """The union of the three classes' newest copies."""
    dated = [(name, taken_at(name)) for name in backups]
    daily = [name for name, when in dated if when is not None]
    weekly = [name for name, when in dated if when is not None and _is_weekly(when)]
    monthly = [name for name, when in dated if when is not None and _is_monthly(when)]
    return set(daily[:DAILY_COPIES]) | set(weekly[:WEEKLY_COPIES]) | set(monthly[:MONTHLY_COPIES])


def _is_weekly(when: datetime) -> bool:
    return when.weekday() == WEEKLY_ON_WEEKDAY


def _is_monthly(when: datetime) -> bool:
    return when.day == MONTHLY_ON_DAY


def wal_to_delete(
    segments: Sequence[tuple[str, datetime]], *, oldest_kept_backup: datetime
) -> tuple[str, ...]:
    """WAL objects that no retained dump could ever be replayed onto.

    A dump with no WAL after it can be restored only to the instant it was taken, which is the
    recovery point this path exists to improve on. So the cut is the oldest dump retention keeps,
    less a margin, and never the newest segment: that one is the deployment's current recovery
    point and the shipper's own evidence that it ran.
    """
    if not segments:
        return ()
    newest = max(segments, key=lambda entry: entry[1])[0]
    cut = oldest_kept_backup.timestamp() - WAL_RETENTION_MARGIN_SECONDS
    return tuple(
        sorted(name for name, when in segments if when.timestamp() < cut and name != newest)
    )
