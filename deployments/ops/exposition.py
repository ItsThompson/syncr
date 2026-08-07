"""Publishing from a process that has exited: one gauge, one file, written atomically.

A one-shot cannot be scraped, so the node exporter's textfile collector is the surface. Two rules
govern it and both are the reason this is a module rather than three lines at a call site:

- **The write is atomic.** The exporter reads the directory on every scrape, on its own schedule,
  and a half-written file is a parse error rather than a missing sample: it sets
  ``node_textfile_scrape_error`` to 1 and DISCARDS EVERY FILE in the directory, which would take the
  learning job's exposition down with the backup's. Write to a temporary name in the same directory
  and rename, which is atomic on the same filesystem.
- **One producer, one file.** The dump's timestamp and the WAL shipper's are separate files, so a
  refused upload in one path cannot rewrite the other's figure. ``BackupStale`` reads both, and the
  whole point of reading both is that they can fail independently.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def write_gauge(directory: Path, *, family: str, help_text: str, value: float) -> Path:
    """Write one gauge to ``<family>.prom`` in the collector's directory, atomically.

    Returns the file written, so a caller can say where the figure went: three separate things break
    between a successful backup and a moved gauge in Prometheus, and they look identical from the
    alert.
    """
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{family}.prom"
    staged = directory / f".{family}.prom.tmp"
    staged.write_text(
        f"# HELP {family} {help_text}\n# TYPE {family} gauge\n{family} {value:.0f}\n",
        encoding="utf-8",
    )
    os.replace(staged, final)
    return final
