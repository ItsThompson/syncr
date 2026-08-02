"""The worker loop: iteration structure, failure isolation, and stop handling."""

from __future__ import annotations

import asyncio

import pytest

from syncr_api.core.db import create_database
from syncr_api.core.settings import WORKER_SERVICE, EnvSettings, build_service_settings
from syncr_api.worker.main import RUNNERS, Runner, WorkerContext, run_forever, run_iteration
from syncr_common.logging import current_correlation_id


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


def test_every_registered_runner_is_callable() -> None:
    # The registry is append-only, so this holds for every runner a later slice adds.
    assert all(callable(runner) for runner in RUNNERS)


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

    failures = await run_iteration(context, runners)

    assert failures == 1
    assert calls == ["projection"]


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
