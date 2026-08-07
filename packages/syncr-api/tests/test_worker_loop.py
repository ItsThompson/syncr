"""The worker loop: iteration structure, failure isolation, and stop handling."""

from __future__ import annotations

import asyncio
import functools
from datetime import UTC, datetime

import pytest

from syncr_api.core.db import create_database
from syncr_api.core.settings import WORKER_SERVICE, EnvSettings, build_service_settings
from syncr_api.worker.main import (
    RUNNERS,
    WORKER_DUTIES,
    Runner,
    WorkerContext,
    run_forever,
    run_iteration,
)
from syncr_common.logging import current_correlation_id
from syncr_common.metrics import REGISTRY


@pytest.fixture
def context() -> WorkerContext:
    """A real context whose engine never connects: the loop itself does no I/O."""
    settings = build_service_settings(service=WORKER_SERVICE, env=EnvSettings(_env_file=None))
    return WorkerContext(settings=settings, database=create_database(settings.database_url))


def counting_runner(calls: list[str], name: str) -> Runner:
    async def runner(_context: WorkerContext) -> None:
        calls.append(name)

    runner.__name__ = name
    return runner


def raising_runner(name: str) -> Runner:
    async def runner(_context: WorkerContext) -> None:
        raise RuntimeError(f"{name} failed")

    runner.__name__ = name
    return runner


def _failure_count(runner: str) -> float:
    sample = REGISTRY.get_sample_value("syncr_worker_runner_failures_total", {"runner": runner})
    return sample or 0.0


def test_every_registered_runner_is_callable() -> None:
    # The registry is append-only, so this holds for every runner a later slice adds.
    assert all(callable(runner) for runner in RUNNERS)


# The five duties one tick runs, in order, and which of them have a body. Spelled out here rather
# than derived from the declaration, because that declaration IS what this asserts: the structure is
# the ticket's own, and a duty renamed, reordered or dropped has to fail rather than be re-read.
ITERATION = [
    ("solve", True),
    ("plan_horizon_maintainer", True),
    ("calendar_sync", True),
    ("projection", True),
    ("maintenance", True),
]


def test_the_iteration_runs_the_five_duties_in_the_documented_order() -> None:
    assert [duty.name for duty in WORKER_DUTIES] == [name for name, _built in ITERATION]


def test_every_duty_now_has_a_body() -> None:
    """The structure stays data a test reads, so a duty declared without a runner still fails here.

    Every one of the five is built now that the solve runner has a body. What the table protects is
    the reverse direction: a duty that loses its runner, or one added without one, reads as a row
    that does nothing rather than as a duty nobody notices is absent.
    """
    built = {duty.name: duty.runner is not None for duty in WORKER_DUTIES}

    assert built == dict(ITERATION)


def test_the_registry_is_the_duties_that_have_a_body() -> None:
    """Plus the periodic work that is not a duty of the plan at all.

    Three runners are in that class: the OAuth expiry sweep, and the two observability readings.
    None of them produces or projects a plan; all three are on the loop because the loop is where
    periodic work happens. Asserted as an exact set difference, so a runner added to the registry
    without a reason stated here fails rather than joining the tick unnoticed.
    """
    from syncr_api.oauth.cleanup import SWEEP_INTERVAL, OAuthSweepRunner
    from syncr_api.observability.config import PRODUCT_INTERVAL, STATE_INTERVAL
    from syncr_api.observability.product_runner import ProductMetricRunner
    from syncr_api.observability.state_runner import StateGaugeRunner

    def clock() -> datetime:
        return datetime.now(UTC)

    beside_the_plan = {
        OAuthSweepRunner(interval=SWEEP_INTERVAL, clock=clock).__name__,
        StateGaugeRunner(interval=STATE_INTERVAL, clock=clock).__name__,
        ProductMetricRunner(interval=PRODUCT_INTERVAL, clock=clock).__name__,
    }
    named = {getattr(runner, "__name__", repr(runner)) for runner in RUNNERS}
    duties = {
        runner.__name__
        for duty in WORKER_DUTIES
        if (runner := duty.runner) is not None and hasattr(runner, "__name__")
    }

    assert duties <= named
    assert named - duties == beside_the_plan


def test_each_runner_that_has_a_body_carries_a_stable_name() -> None:
    # The loop labels its failure counter with this. A runner whose name changed per instance would
    # spread one duty's failures over a growing label set.
    for duty in WORKER_DUTIES:
        if duty.runner is not None:
            assert getattr(duty.runner, "__name__", None), duty.name


async def test_one_iteration_runs_every_runner_in_declaration_order(
    context: WorkerContext,
) -> None:
    calls: list[str] = []
    runners = [counting_runner(calls, "solve"), counting_runner(calls, "projection")]

    failures = await run_iteration(context, runners)

    assert calls == ["solve", "projection"]
    assert failures == 0


async def test_a_failing_runner_does_not_stop_the_others(context: WorkerContext) -> None:
    calls: list[str] = []
    runners = [raising_runner("calendar_sync"), counting_runner(calls, "projection")]
    before = _failure_count("calendar_sync")

    failures = await run_iteration(context, runners)

    assert failures == 1
    assert calls == ["projection"]
    # The loop swallows the exception so the other duties run, so `measured` records
    # no error and the failure would otherwise be invisible to monitoring.
    assert _failure_count("calendar_sync") == before + 1


async def test_a_failing_runner_without_a_name_does_not_take_the_loop_down(
    context: WorkerContext,
) -> None:
    # A partial is a legal registry entry and has no __name__. Reading it unguarded
    # inside the handler that exists to isolate failures would unwind the loop and exit
    # the process, which under `restart: unless-stopped` is a crash loop.
    async def sync_source(_context: WorkerContext, source_id: str) -> None:
        raise RuntimeError(f"{source_id} failed")

    nameless = functools.partial(sync_source, source_id="ics-1")
    assert not hasattr(nameless, "__name__")
    calls: list[str] = []

    failures = await run_iteration(context, [nameless, counting_runner(calls, "projection")])

    assert failures == 1
    assert calls == ["projection"], "a nameless runner's failure must not stop the others"


async def test_a_nameless_runner_is_still_counted(context: WorkerContext) -> None:
    async def raise_it(_context: WorkerContext) -> None:
        raise RuntimeError("boom")

    class Duty:
        """A callable object, which is what a service-backed runner will look like."""

        async def __call__(self, context: WorkerContext) -> None:
            await raise_it(context)

    duty = Duty()
    before = _failure_count(repr(duty))

    assert await run_iteration(context, [duty]) == 1
    assert _failure_count(repr(duty)) == before + 1


async def test_the_loop_runs_a_bounded_number_of_iterations(context: WorkerContext) -> None:
    calls: list[str] = []

    iterations = await run_forever(
        context,
        runners=[counting_runner(calls, "solve")],
        tick_seconds=0.01,
        max_iterations=3,
    )

    assert iterations == 3
    assert calls == ["solve", "solve", "solve"]


async def test_a_zero_iteration_bound_runs_nothing(context: WorkerContext) -> None:
    calls: list[str] = []

    iterations = await run_forever(
        context, runners=[counting_runner(calls, "solve")], max_iterations=0
    )

    assert iterations == 0
    assert calls == []


async def test_an_empty_registry_still_ticks(context: WorkerContext) -> None:
    assert await run_forever(context, runners=(), tick_seconds=0.01, max_iterations=2) == 2


async def test_a_stop_signal_ends_the_loop_without_waiting_out_the_tick(
    context: WorkerContext,
) -> None:
    stop = asyncio.Event()
    calls: list[str] = []

    async def stopping_runner(_context: WorkerContext) -> None:
        calls.append("tick")
        stop.set()

    iterations = await asyncio.wait_for(
        run_forever(context, runners=[stopping_runner], tick_seconds=3600, stop=stop),
        timeout=5,
    )

    assert iterations == 1
    assert calls == ["tick"]


async def test_each_iteration_binds_a_fresh_correlation_id(context: WorkerContext) -> None:
    seen: list[str | None] = []

    async def recording_runner(_context: WorkerContext) -> None:
        seen.append(current_correlation_id())

    await run_forever(context, runners=[recording_runner], tick_seconds=0.01, max_iterations=2)

    assert all(seen), "every tick must bind a correlation id"
    assert seen[0] != seen[1], "a tick must not inherit the previous tick's id"


async def test_the_closing_line_carries_no_tick_correlation_id(context: WorkerContext) -> None:
    # A lifecycle event belongs to no unit of work, so attributing it to the last
    # tick's id would send anyone tracing that id to the wrong place.
    await run_forever(context, runners=(), tick_seconds=0.01, max_iterations=1)

    assert current_correlation_id() is None
