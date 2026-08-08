"""The container's ``main``: configure logging, build the adapter, run once, exit with the verdict.

**The exit code is the whole point of this module.** A failed fit exits non-zero so the container's
failure is visible to the monitoring stack rather than silently producing no new version. Section 19
pairs that exit with an info alert and the observation that the previous active weight set stays in
place, which is a benign degradation: the solver keeps working with slightly older parameters.

A one-shot, not a service. There is no server, no loop and no signal handling: the container runs,
the timer that started it collects the code, and the process is gone. What it does hold is the
metric exposition, written to a file the node exporter's textfile collector reads, because a process
that has exited cannot be scraped.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from syncr_common.logging import configure_logging, get_logger
from syncr_common.metrics import render
from syncr_learning.job import promotion_candidates, run
from syncr_learning.storage.engine import LearningSettings, create_database
from syncr_learning.storage.reader import PostgresCorpusReader
from syncr_learning.storage.writer import PostgresParameterWriter

if TYPE_CHECKING:
    from syncr_learning.job import RunReport

_log = get_logger("syncr.learning")

EXIT_OK = 0
EXIT_FAILED = 1


async def run_once(settings: LearningSettings, *, at: datetime) -> RunReport:
    """One nightly pass, against the database ``settings`` names. Disposes what it built."""
    database = create_database(settings.database_url)
    try:
        return await run(
            PostgresCorpusReader(database.sessions, now=at),
            PostgresParameterWriter(database.sessions),
            at=at,
        )
    finally:
        await database.engine.dispose()


def main() -> int:
    """The container's entrypoint. Non-zero when any tenant's pass failed."""
    settings = LearningSettings()
    configure_logging(environment=settings.environment, log_level=settings.log_level)
    at = datetime.now(UTC)
    report = asyncio.run(run_once(settings, at=at))
    for candidate in promotion_candidates(report):
        _log.info(
            "learning.promotion.candidate",
            promotion_id=candidate.ref.id,
            kind=candidate.ref.kind.value,
            entity_id=str(candidate.ref.entity_id),
            weekday=candidate.ref.weekday,
            local_time=candidate.ref.local_time,
            consecutive_weeks=candidate.consecutive_weeks,
        )
    _write_exposition(settings)
    if report.failed:
        for failure in report.failures:
            _log.error("learning.run.failed", detail=failure)
        return EXIT_FAILED
    return EXIT_OK


def _write_exposition(settings: LearningSettings) -> None:
    """Write the run's metrics where the node exporter's textfile collector will find them.

    A one-shot cannot be scraped: it has exited by the time a scrape would arrive. Written to a
    temporary path and moved into place, so a collector reading mid-write sees the previous file
    rather than half of this one.

    A failure here is logged and swallowed. The metrics describe a run that has already happened,
    and losing them must not turn a successful night into a non-zero exit: the exit code is about
    the fit.
    """
    target = _exposition_path(settings)
    if target is None:
        return
    body, _ = render()
    staging = target.with_suffix(".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(body)
        staging.replace(target)
    except OSError as error:
        _log.warning("learning.metrics.unwritable", path=str(target), error=str(error))


def _exposition_path(settings: LearningSettings) -> Path | None:
    """Where the exposition goes, or nothing because this deployment does not collect it."""
    directory = settings.textfile_collector_dir.strip()
    return Path(directory) / "syncr_learning.prom" if directory else None


if __name__ == "__main__":
    sys.exit(main())
