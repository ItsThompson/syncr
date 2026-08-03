"""The expiry sweep's cadence, and its place on the worker loop.

The sweep itself is proven against real Postgres in ``test_oauth_flow_integration.py``. What is
proven here is the runner around it: that it is registered, that it does not sweep on its first
tick, and that it sweeps once per interval rather than once per tick.

The first-tick rule matters more than it looks. The worker ticks every few seconds, and a
container that restarts under `restart: unless-stopped` starts a fresh runner every time, so a
runner that swept immediately would turn a crash loop into a delete loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syncr_api.oauth.cleanup import SWEEP_INTERVAL, OAuthSweepRunner, SweptRows
from syncr_api.worker.main import RUNNERS, WorkerContext, run_iteration

START = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


class MovableClock:
    def __init__(self, at: datetime) -> None:
        self.now = at

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


class CountingSessions:
    """Records how many sessions were opened, which is how many sweeps really ran.

    Answers the tenant enumeration with nothing, so a sweep completes without a database and
    what is measured is the cadence rather than the deletion. The deletion is proven against
    real Postgres in ``test_oauth_flow_integration.py``.
    """

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> CountingSessions:
        self.opened += 1
        return self

    async def __aenter__(self) -> CountingSessions:
        return self

    async def __aexit__(self, *_exit: object) -> None:
        return None

    def begin(self) -> CountingSessions:
        return self

    async def scalars(self, _statement: object) -> list[object]:
        return []


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock(START)


@pytest.fixture
def sessions() -> CountingSessions:
    return CountingSessions()


@pytest.fixture
def context(sessions: CountingSessions, settings: object) -> WorkerContext:
    class _Database:
        sessionmaker = sessions

    return WorkerContext(settings=settings, database=_Database())  # type: ignore[arg-type]


async def test_the_runner_is_on_the_worker_loop() -> None:
    # Nothing else invokes the sweep, so a runner that is not registered is a table that grows
    # forever with nobody reading it.
    assert any(isinstance(runner, OAuthSweepRunner) for runner in RUNNERS)


async def test_the_first_tick_schedules_rather_than_sweeping(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    runner = OAuthSweepRunner(interval=SWEEP_INTERVAL, clock=clock)

    await runner(context)

    assert sessions.opened == 0
    assert runner.next_due_at == START + SWEEP_INTERVAL


async def test_a_tick_before_the_interval_does_nothing(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    runner = OAuthSweepRunner(interval=SWEEP_INTERVAL, clock=clock)
    await runner(context)

    clock.advance(SWEEP_INTERVAL - timedelta(seconds=1))
    await runner(context)

    assert sessions.opened == 0


async def test_a_tick_at_the_interval_sweeps_and_reschedules(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    runner = OAuthSweepRunner(interval=SWEEP_INTERVAL, clock=clock)
    await runner(context)
    clock.advance(SWEEP_INTERVAL)

    await runner(context)

    assert sessions.opened == 1
    assert runner.next_due_at == START + SWEEP_INTERVAL + SWEEP_INTERVAL


async def test_many_ticks_produce_one_sweep_per_interval(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    # The property the cadence exists for: the loop's resolution is not the sweep's schedule.
    runner = OAuthSweepRunner(interval=SWEEP_INTERVAL, clock=clock)
    for _tick in range(200):
        await runner(context)
        clock.advance(timedelta(seconds=30))

    # 200 ticks of 30 seconds is 100 minutes, which holds six whole quarter-hour intervals after
    # the first tick schedules the seventh.
    assert sessions.opened == 6


async def test_a_failing_sweep_does_not_stop_the_loop(context: WorkerContext) -> None:
    # The loop's own contract, asserted through this runner: one failing duty must not take the
    # others down, and the worker counts the failure rather than exiting.
    class _Failing(OAuthSweepRunner):
        async def __call__(self, _context: WorkerContext) -> None:
            raise RuntimeError("the database went away")

    failures = await run_iteration(
        context, [_Failing(interval=SWEEP_INTERVAL, clock=lambda: START)]
    )

    assert failures == 1


def test_a_tally_reports_what_each_pass_removed() -> None:
    combined = SweptRows(codes=1, refresh_tokens=2).plus(SweptRows(grants=3))

    assert combined == SweptRows(codes=1, refresh_tokens=2, grants=3)
    assert combined.total == 6
    assert SweptRows().total == 0
