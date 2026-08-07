"""Is this file a dump that would actually restore? Asked in three ways, because one is not enough.

The failure this module exists for is a backup path that reports success and produces nothing
usable: ``pg_dump`` exiting 0 into a full disk, a pipe closed mid-stream, a dump taken against the
wrong database, or a ``--schema-only`` run that copies every table definition and no row.

- **The archive header** catches an empty file, a text-format dump, and anything that is not a dump.
- **``pg_restore --list`` exiting non-zero** catches a truncated body, which the header cannot see:
  the header of a 200-byte fragment is intact.
- **The tables the listing names** catches a dump of the wrong database and a schema-only dump,
  neither of which is short or malformed.

The third is the only one of the three that reads the dump against what the deployment expects to be
in it, which is why the tables it requires come from the fingerprint the api image wrote rather than
from a list here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

# `PGDMP` then vmaj, vmin, vrev, intSize, offSize, format. Read from a real 16.10 dump rather than
# from memory: `PGDMP 01 0f 00 04 08 01`, which is archive version 1.15-0, 4-byte integers, 8-byte
# offsets, format 1.
_MAGIC: Final = b"PGDMP"
_HEADER_BYTES: Final = 11
_CUSTOM_FORMAT: Final = 1

# A custom-format dump of this schema with every table empty is over 100 KB, almost all of it the
# schema. The floor is far below that on purpose: its job is to separate "nothing was written" from
# "something was", and the two readings below are what judge whether that something is usable.
MIN_DUMP_BYTES: Final = 1024

# `3775; 0 16389 TABLE DATA public alembic_version syncr`, as `pg_restore --list` prints it.
_TABLE_DATA = re.compile(r"^\d+;\s+\d+\s+\d+\s+TABLE DATA\s+(?P<schema>\S+)\s+(?P<table>\S+)\s")


class DumpUnusable(Exception):
    """The file is not a dump this deployment could restore, and the message says which way."""


@dataclass(frozen=True, slots=True)
class Header:
    """What the archive says about itself."""

    version: str
    integer_bytes: int
    offset_bytes: int


def read_header(path: Path) -> Header:
    """The archive header, or a refusal naming what the file is instead."""
    size = path.stat().st_size if path.exists() else 0
    if size < MIN_DUMP_BYTES:
        raise DumpUnusable(
            f"{path} is {size} bytes, under the {MIN_DUMP_BYTES}-byte floor. A dump that succeeded "
            "and wrote nothing is the failure this check exists for: look for a full disk or a "
            "closed pipe before looking at Postgres."
        )
    opened = path.open("rb").read(_HEADER_BYTES)
    if not opened.startswith(_MAGIC):
        raise DumpUnusable(
            f"{path} does not begin with {_MAGIC.decode()}, so it is not a Postgres archive. A "
            "plain-text dump cannot be restored selectively and is not what this path writes."
        )
    if opened[10] != _CUSTOM_FORMAT:
        raise DumpUnusable(
            f"{path} is archive format {opened[10]}, not custom ({_CUSTOM_FORMAT}). The restore "
            "procedure and every figure in it assume --format=custom."
        )
    return Header(
        version=f"{opened[5]}.{opened[6]}-{opened[7]}",
        integer_bytes=opened[8],
        offset_bytes=opened[9],
    )


def data_tables(listing: str) -> frozenset[str]:
    """Every table the listing carries a data entry for, schema-qualified.

    Read from ``pg_restore --list``, which is also the reading whose EXIT STATUS catches a truncated
    body: the archive header of a fragment is intact, so nothing about the first bytes of a file can
    tell you the rest of it arrived.
    """
    return frozenset(
        f"{found.group('schema')}.{found.group('table')}"
        for line in listing.splitlines()
        if (found := _TABLE_DATA.match(line)) is not None
    )


def require_tables(listing: str, *, expected: frozenset[str]) -> None:
    """Refuse a dump that does not carry a data entry for every table the fingerprint counted.

    ``expected`` comes from the manifest the api image wrote against the live database, so this is
    the one reading that crosses the dump against what the deployment believes is in it. A dump of
    the wrong database, and a ``--schema-only`` dump, are both well-formed and both fail here.
    """
    missing = expected - data_tables(listing)
    if missing:
        raise DumpUnusable(
            f"the dump carries no data entry for {sorted(missing)}, which the fingerprint counted "
            "rows in. Either it was taken against another database or it is schema-only."
        )
