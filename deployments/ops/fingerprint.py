"""The fingerprint, read from the other side of the bucket.

The api image writes this document; this reads it. There is no import between the two: one runs
Python 3.12 with the application installed, the other Python 3.11 in an image built from Postgres.
So the key names below are the contract, and
``packages/syncr-api/tests/test_recovery_fingerprint.py`` crosses them against the writer's own
constants as an equality. A renamed key fails a gate rather than a drill at 03:00.

**Reading is strict.** A missing key, a count that is not an integer, and a cursor with no index are
all refusals. The alternative is a comparison that silently treats an unreadable document as an
empty one, which is the same defect as a restore that succeeds and comes back empty.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from pathlib import Path

KEY_VERSION: Final = "version"
KEY_TAKEN_AT: Final = "taken_at"
KEY_EXPECTED_HEAD: Final = "expected_head"
KEY_APPLIED_REVISION: Final = "applied_revision"
KEY_ROW_COUNTS: Final = "row_counts"
KEY_DIGESTS: Final = "content_digests"
KEY_CURSORS: Final = "cursors"
KEY_CURSOR_KEY: Final = "key"
KEY_CURSOR_INDEX: Final = "index"
KEY_CURSOR_VARIANT: Final = "variant"
KEY_CURSOR_COMPLETIONS: Final = "confirmed_completions"

DOCUMENT_KEYS: Final = frozenset(
    {
        KEY_VERSION,
        KEY_TAKEN_AT,
        KEY_EXPECTED_HEAD,
        KEY_APPLIED_REVISION,
        KEY_ROW_COUNTS,
        KEY_DIGESTS,
        KEY_CURSORS,
    }
)
CURSOR_KEYS: Final = frozenset(
    {KEY_CURSOR_KEY, KEY_CURSOR_INDEX, KEY_CURSOR_VARIANT, KEY_CURSOR_COMPLETIONS}
)


class FingerprintUnreadable(Exception):
    """The document is not a fingerprint this comparison can be stated over."""


@dataclass(frozen=True, slots=True)
class Cursor:
    """One rotation habit's derived cursor, as the document carries it."""

    key: str
    index: int
    variant: str
    confirmed_completions: int


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """One reading of one database."""

    taken_at: datetime
    expected_head: str
    applied_revision: str | None
    row_counts: dict[str, int]
    content_digests: dict[str, str]
    cursors: tuple[Cursor, ...]

    @property
    def tables(self) -> frozenset[str]:
        """Every table this reading names, which is what a dump must carry data entries for."""
        return frozenset(self.row_counts)

    @property
    def rows(self) -> int:
        """Every row, over every table."""
        return sum(self.row_counts.values())

    def cursor_by_key(self) -> dict[str, Cursor]:
        return {cursor.key: cursor for cursor in self.cursors}


def read(path: Path) -> Fingerprint:
    """Parse one fingerprint document, or refuse with what is wrong with it."""
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        raise FingerprintUnreadable(f"{path}: {unreadable}") from unreadable
    if not isinstance(document, dict):
        raise FingerprintUnreadable(f"{path} is not a JSON object")
    missing = DOCUMENT_KEYS - set(document)
    if missing:
        raise FingerprintUnreadable(f"{path} is missing {sorted(missing)}")
    return Fingerprint(
        taken_at=_instant(document[KEY_TAKEN_AT], path),
        expected_head=str(document[KEY_EXPECTED_HEAD]),
        applied_revision=_optional_text(document[KEY_APPLIED_REVISION]),
        row_counts=_counts(document[KEY_ROW_COUNTS], path),
        content_digests=_digests(document[KEY_DIGESTS], path),
        cursors=_cursors(document[KEY_CURSORS], path),
    )


def _instant(stated: Any, path: Path) -> datetime:
    try:
        return datetime.fromisoformat(str(stated))
    except ValueError as unreadable:
        raise FingerprintUnreadable(f"{path} carries {stated!r} as an instant") from unreadable


def _optional_text(stated: Any) -> str | None:
    return None if stated is None else str(stated)


def _counts(stated: Any, path: Path) -> dict[str, int]:
    if not isinstance(stated, dict) or not stated:
        raise FingerprintUnreadable(f"{path} carries no row counts, so nothing can be compared")
    found: dict[str, int] = {}
    for table, count in stated.items():
        if not isinstance(count, int) or isinstance(count, bool):
            raise FingerprintUnreadable(f"{path} carries {count!r} as the count for {table}")
        found[str(table)] = count
    return found


def _digests(stated: Any, path: Path) -> dict[str, str]:
    """Every table's content digest, refusing a document that carries none.

    Strict for the same reason the counts are: an empty digest map would compare equal to another
    empty one, and the comparison it feeds is the only one in the verdict that can see a row's
    bytes.
    """
    if not isinstance(stated, dict) or not stated:
        raise FingerprintUnreadable(
            f"{path} carries no content digests, so nothing about the rows themselves is comparable"
        )
    found: dict[str, str] = {}
    for table, digest in stated.items():
        if not isinstance(digest, str) or not digest:
            raise FingerprintUnreadable(f"{path} carries {digest!r} as the digest for {table}")
        found[str(table)] = digest
    return found


def _cursors(stated: Any, path: Path) -> tuple[Cursor, ...]:
    if not isinstance(stated, list):
        raise FingerprintUnreadable(f"{path} carries {type(stated).__name__} as its cursor list")
    found = []
    for entry in stated:
        if not isinstance(entry, dict) or CURSOR_KEYS - set(entry):
            raise FingerprintUnreadable(f"{path} carries an incomplete cursor: {entry!r}")
        found.append(
            Cursor(
                key=str(entry[KEY_CURSOR_KEY]),
                index=int(entry[KEY_CURSOR_INDEX]),
                variant=str(entry[KEY_CURSOR_VARIANT]),
                confirmed_completions=int(entry[KEY_CURSOR_COMPLETIONS]),
            )
        )
    return tuple(found)
