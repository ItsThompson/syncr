"""The cooperative checkpoint: a flag the solver can read while a poller watches the version row.

Cancellation is an OPTIMIZATION and nothing else. Correctness is the conditional write, which
refuses a plan whose input version has moved, so a solve that stops early and one that finishes are
both discarded when nobody wants the result. What this buys is the worker's time back: a solve whose
result is already doomed gives up in a few milliseconds instead of spending the rest of its budget.

**The solver's predicate cannot await, and that is what shapes this module.**
``syncr_solver.solve`` takes ``Callable[[], bool]`` and calls it from inside synchronous search, so
it can neither open a session nor read a row. So the solve runs in a worker thread and the version
is polled on the event loop, which sets a plain flag the predicate reads. The interpreter switches
between the two often enough for the poll to run: a pure-Python solve releases the interpreter lock
on its own schedule, and the poll interval is far longer than that.

**Running the solve off the loop is worth having on its own.** A 1.4-second synchronous solve on the
event loop blocks every other duty of the tick, including the poll that would notice a supersession.

**The poller reads with its own session** and never inside the caller's transaction. It reads a
counter, so a snapshot per read is exactly what it wants, and sharing a session with the assembly
would either hold that transaction open across the solve or read a value frozen at its start.

**A poll that raises stops the watch rather than the solve.** The predicate then answers False for
the rest of the solve, which is the state the product had before any checkpoint existed: the
conditional write still refuses a stale plan.
"""

from __future__ import annotations

import asyncio
import contextlib
from threading import Event
from typing import TYPE_CHECKING, Final

from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

# How often the version row is read while a solve runs. The solve is budgeted at under two seconds
# and asks its own question every fiftieth move, so ten polls across a whole solve is enough to stop
# one early while costing one indexed read each.
POLL_INTERVAL_SECONDS: Final = 0.2

_log = get_logger("syncr.solving")


@contextlib.asynccontextmanager
async def watching_the_version(
    sessionmaker: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    iso_week: IsoWeek,
    *,
    held: int,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> AsyncIterator[Callable[[], bool]]:
    """A predicate that answers True once ``iso_week``'s version has moved past ``held``.

    The poller starts on entry and is stopped on exit, whether the body returned or raised, so a
    solve that fails leaves no task reading a row nobody is waiting on.
    """
    moved = Event()
    poller = asyncio.create_task(
        _poll(
            sessionmaker,
            tenant_id,
            iso_week,
            held=held,
            moved=moved,
            every=poll_interval_seconds,
        )
    )
    try:
        yield moved.is_set
    finally:
        poller.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller


async def _poll(
    sessionmaker: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    iso_week: IsoWeek,
    *,
    held: int,
    moved: Event,
    every: float,
) -> None:
    """Read the week's version until it differs from ``held``, then set the flag and stop."""
    while True:
        await asyncio.sleep(every)
        try:
            async with sessionmaker() as session:
                current = await WeekInputVersionRepository(session, tenant_id).current(iso_week)
        except Exception:  # noqa: BLE001 - a checkpoint is an optimization, not a guard
            _log.exception("solving.checkpoint.unreadable", iso_week=str(iso_week))
            return
        if current is not None and current != held:
            moved.set()
            _log.info(
                "solving.checkpoint.superseded",
                iso_week=str(iso_week),
                held=held,
                current=current,
            )
            return
