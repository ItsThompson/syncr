"""The worker entrypoint and its iteration loop.

The worker is an entrypoint of ``syncr-api`` rather than a package of its own,
because it needs the same repositories, the same ORM session handling, and the same
settings. A separate package would duplicate persistence or invert the dependency.

The loop is defined here once so a later slice adds a runner rather than inventing
its own scheduling. One iteration is:

    1. clear the log context, then bind a fresh correlation id for this tick, so
       every line a runner emits during the tick is traceable to it
    2. call each registered runner in declaration order, awaiting each. Runners are
       serial rather than concurrent because they share one bounded connection pool
       and Postgres runs without a pooler
    3. a runner that raises is logged and counted on
       ``syncr_worker_runner_failures_total``, and the loop continues: one failing
       duty must not stop the others
    4. sleep out the tick interval, or exit immediately if a stop signal arrived

A runner owns its own cadence and decides per tick whether it has work. The tick is
the loop's resolution, not any runner's schedule.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.calendars.config import SYNC_INTERVAL
from syncr_api.calendars.runner import CalendarSyncRunner
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database
from syncr_api.core.settings import WORKER_SERVICE, ServiceSettings, build_service_settings
from syncr_api.oauth.cleanup import SWEEP_INTERVAL, OAuthSweepRunner
from syncr_common.logging import (
    bind_correlation_id,
    clear_context,
    configure_logging,
    get_logger,
    new_correlation_id,
)
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from syncr_api.core.db import Database

# How often the loop wakes. Short enough that a debounced solve is picked up
# promptly, long enough that an idle worker is idle.
TICK_SECONDS = 5.0

# `measured` counts an error only when the decorated call raises, and an iteration
# deliberately never does, so a duty that fails every tick would otherwise leave every
# worker counter at zero while the loop reported healthy.
RUNNER_FAILURES = Counter(
    "syncr_worker_runner_failures_total",
    "Worker runners that exited by raising, by runner.",
    labelnames=("runner",),
    registry=REGISTRY,
)


@dataclass(frozen=True)
class WorkerContext:
    """What every runner is handed: settings and the database. No HTTP anything."""

    settings: ServiceSettings
    database: Database


# A runner does one tick of one duty and returns. It reports "nothing to do" by
# returning, not by raising.
type Runner = Callable[[WorkerContext], Awaitable[None]]

# ---------------------------------------------------------------------------
# THE RUNNER REGISTRY. APPEND ONLY.
#
# One line per duty, added at the END of this tuple: the solve runner, the calendar
# sync scheduler, the projection writer, the plan horizon maintainer. Written
# multi-line while empty so the first appending ticket adds a line rather than
# reformatting the one every later ticket then edits.
# ---------------------------------------------------------------------------
RUNNERS: tuple[Runner, ...] = (
    # run_solve_runner,
    OAuthSweepRunner(interval=SWEEP_INTERVAL, clock=utc_now),
    CalendarSyncRunner(interval=SYNC_INTERVAL, clock=utc_now),
)

_log = get_logger(WORKER_SERVICE)


@measured("worker")
async def run_iteration(context: WorkerContext, runners: Sequence[Runner]) -> int:
    """Run one tick of every runner. Returns how many raised."""
    clear_context()
    bind_correlation_id(new_correlation_id())
    failures = 0
    for runner in runners:
        # A Runner is any awaitable callable, so a partial, a callable object, or a
        # closure from a factory is a legal registry entry and none of those is
        # guaranteed to carry `__name__`. Resolving it defensively matters because this
        # runs INSIDE the handler that exists to isolate one duty's failure: an
        # AttributeError here would escape the except block, unwind the loop, and exit
        # the process, which under `restart: unless-stopped` is a crash loop.
        name = getattr(runner, "__name__", repr(runner))
        try:
            await runner(context)
        except Exception:  # noqa: BLE001 - one failing duty must not stop the others
            failures += 1
            RUNNER_FAILURES.labels(runner=name).inc()
            _log.exception("worker.runner.failed", runner=name)
    return failures
    return failures


async def _wait_for_tick(stop: asyncio.Event, tick_seconds: float) -> None:
    """Sleep out the tick, waking early if a stop signal arrives."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=tick_seconds)


async def run_forever(
    context: WorkerContext,
    *,
    runners: Sequence[Runner] = RUNNERS,
    tick_seconds: float = TICK_SECONDS,
    stop: asyncio.Event | None = None,
    max_iterations: int | None = None,
) -> int:
    """Tick until ``stop`` is set or ``max_iterations`` ticks have run.

    ``max_iterations`` bounds the loop for a test and for a one-shot invocation; the
    container leaves it unset and stops the loop with a signal instead. It is
    checked again after the iteration so a bounded run does not sleep out a final
    tick it will never use.
    """
    stop = stop or asyncio.Event()
    iterations = 0
    _log.info("worker.loop.started", runners=len(runners), tick_seconds=tick_seconds)
    while not stop.is_set() and iterations != max_iterations:
        await run_iteration(context, runners)
        iterations += 1
        if iterations == max_iterations:
            break
        await _wait_for_tick(stop, tick_seconds)
    # Clear before the closing line so a lifecycle event is not attributed to the
    # last tick's unit of work.
    clear_context()
    _log.info("worker.loop.stopped", iterations=iterations)
    return iterations


def build_context() -> WorkerContext:
    """Compose the worker's context from the ambient environment."""
    settings = build_service_settings(service=WORKER_SERVICE)
    return WorkerContext(settings=settings, database=create_database(settings.database_url))


async def serve(context: WorkerContext) -> None:
    """Run the loop until SIGTERM or SIGINT, then dispose the connection pool."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for received in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(received, stop.set)

    try:
        await run_forever(context, stop=stop)
    finally:
        await context.database.engine.dispose()


def main() -> None:
    """The container entrypoint."""
    context = build_context()
    configure_logging(
        environment=context.settings.environment, log_level=context.settings.log_level
    )
    asyncio.run(serve(context))
