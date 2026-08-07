"""The two database families: the pool gauge and the per-repository read histogram.

Section 18 names ``syncr_db_pool_in_use`` and ``syncr_db_query_duration_seconds``. Neither was
declared by anything, so the System dashboard's "database pool and query duration" had nothing to
draw and a connection pool running at its ceiling was invisible.

## The pool gauge is a COLLECT-TIME reading, not a value something sets

A gauge that a caller sets is a gauge that is absent, or stale, exactly when the thing it measures
is in trouble: a process saturating its pool is a process not reaching whatever line would have set
it. So the pool is read by the client library at scrape time, from the pool itself, through
``Gauge.set_function``. Nothing has to remember to update it and there is no path on which it goes
missing.

## The read histogram is derived from the repository base, not from a list

Every repository over a tenant-scoped table extends :class:`~syncr_api.core.repository.
TenantScopedReader`, so wrapping its public coroutine methods instruments whatever repositories
exist rather than whatever a decorator was remembered on. A repository added by a later ticket is
measured with no change here.

**It measures the repository METHOD, which is not always one statement.** The label pair section 18
states is repository and method, so that is the unit: a method issuing four statements is one
observation, and the count is calls rather than queries. That is the reading an operator can act on,
because a method is what a call site names.

The buckets are stated rather than left at the client library's defaults, and they are the latency
budgets in section 19: a read that has crossed 100 ms is the assembly's whole budget spent in one
call. Stating them also bounds the exposition, which carries one line per bucket per series.
"""

from __future__ import annotations

import functools
import inspect
import time
from typing import TYPE_CHECKING, Final

from prometheus_client import Gauge, Histogram
from sqlalchemy.pool import QueuePool

from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.pool import Pool

# Bounded to the latency budgets a database read is measured against, rather than the client
# library's defaults, which run to 10 seconds and cost a line per bucket per series.
READ_BUCKETS: Final = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf"))

POOL_IN_USE = Gauge(
    "syncr_db_pool_in_use",
    "Connections checked out of this process's pool, read at scrape time.",
    registry=REGISTRY,
)

READ_DURATION = Histogram(
    "syncr_db_query_duration_seconds",
    "Wall time of one repository method, including every statement it issues.",
    labelnames=("repository", "method"),
    buckets=READ_BUCKETS,
    registry=REGISTRY,
)


def observe_pool(engine: AsyncEngine) -> None:
    """Have ``syncr_db_pool_in_use`` read this engine's pool on every scrape.

    Called once per process by whatever composed the engine. A second call replaces the reading,
    which is what a test building its own engine wants and what a process with one engine never
    does.
    """
    pool = engine.sync_engine.pool
    POOL_IN_USE.set_function(lambda: _checked_out(pool))


def _checked_out(pool: Pool) -> float:
    """Connections this pool has handed out.

    Zero for a pool that holds none. Every engine this application builds is pooled, so the other
    branch exists to keep the gauge readable rather than to describe a deployment.
    """
    return float(pool.checkedout()) if isinstance(pool, QueuePool) else 0.0


def measure_reads[ClassT: type](cls: ClassT) -> ClassT:
    """Wrap every public coroutine method this class DEFINES so each call is timed.

    Applied to the scoped repository base through ``__init_subclass__``, and directly to a
    repository over an identity table, which is not scoped and so does not extend that base.

    Only methods in the class's own ``__dict__`` are wrapped, so a method inherited from another
    repository is timed once, under the class that defined it.
    """
    for name, attribute in list(vars(cls).items()):
        if name.startswith("_") or not inspect.iscoroutinefunction(attribute):
            continue
        setattr(cls, name, _timed(cls.__name__, name, attribute))
    return cls


def _timed[**P, R](
    repository: str, method: str, call: Callable[P, Awaitable[R]]
) -> Callable[P, Awaitable[R]]:
    observed = READ_DURATION.labels(repository=repository, method=method)

    @functools.wraps(call)
    async def timed(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.perf_counter()
        try:
            return await call(*args, **kwargs)
        finally:
            # Timed on every exit, including a raise: a read that fails after a lock wait is one an
            # operator wants in the latency reading rather than silently dropped from it.
            observed.observe(time.perf_counter() - started)

    return timed
