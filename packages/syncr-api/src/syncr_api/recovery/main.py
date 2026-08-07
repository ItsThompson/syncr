"""The ``syncr-plan-fingerprint`` console script: describe a database into one JSON file.

Run twice per restore drill, in the same image, against two databases: the live one before the dump
is taken, and the restored copy after migrations have been applied to it. The comparison is
``python3 -m ops.compare``, on the other side of the bucket.

Exit codes: 0 when the document was written, 1 when the output path was not stated or the database
could not be read. A refusal writes nothing, so a stale document from an earlier run cannot be
mistaken for this run's: the dump step requires the file to be recent and says so by name.

The write is atomic, for the same reason the textfile exposition is: the reader is another process
on a schedule, and half a document is worse than none.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database
from syncr_api.core.migrations import applied_revision, expected_head
from syncr_api.core.settings import EnvSettings
from syncr_api.recovery.fingerprint import read_fingerprint
from syncr_common.logging import configure_logging

PATH_ENV_VAR = "SYNCR_FINGERPRINT_PATH"

EXIT_OK = 0
EXIT_REFUSED = 1


def main() -> None:
    """Entry point for the ``syncr-plan-fingerprint`` console script."""
    settings = EnvSettings()
    configure_logging(environment=settings.environment, log_level=settings.log_level)
    sys.exit(asyncio.run(run(settings)))


async def run(settings: EnvSettings) -> int:
    """Read the database and write the document, or say why not."""
    stated = os.environ.get(PATH_ENV_VAR, "").strip()
    if not stated:
        print(f"{PATH_ENV_VAR} must name the file to write", file=sys.stderr)
        return EXIT_REFUSED

    database = create_database(settings.database_url)
    try:
        applied = await applied_revision(database.engine)
        async with database.sessionmaker() as session:
            fingerprint = await read_fingerprint(
                session,
                now=utc_now(),
                expected_head=expected_head(),
                applied_revision=applied,
            )
    except (SQLAlchemyError, OSError) as unreachable:
        print(f"the database could not be read: {unreachable}", file=sys.stderr)
        return EXIT_REFUSED
    finally:
        await database.engine.dispose()

    written = write_document(Path(stated), fingerprint.as_document())
    total = sum(fingerprint.row_counts.values())
    print(
        f"wrote {written}: {len(fingerprint.row_counts)} tables, {total} rows, "
        f"{len(fingerprint.cursors)} rotation cursors, revision {applied or 'nothing'}"
    )
    return EXIT_OK


def write_document(path: Path, document: dict[str, object]) -> Path:
    """Write the document atomically, so a reader never sees half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.tmp")
    staged.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staged, path)
    return path
