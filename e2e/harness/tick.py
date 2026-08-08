#!/usr/bin/env python3
"""Tick the plan-horizon maintainer once, now.

Run as a one-shot in the api image, which is where the runner lives::

    docker compose -f docker-compose.yml -f e2e/docker-compose.e2e.yml \\
      run --rm --no-deps worker python /harness/tick.py

S1 says "wait for the plan-horizon maintainer's next tick, or trigger it". This is the trigger,
and it exists because the wait is fifteen minutes: ``PlanHorizonRunner`` returns without planning
on its FIRST tick and sets its own due time to ``now + MAINTAINER_INTERVAL``, so a worker that has
just started has not yet planned anything and will not for a quarter of an hour.

IT DRIVES THE REAL RUNNER, over the real database, through the worker's own iteration. The
interval is zero rather than fifteen minutes, which is the only substitution: the first iteration
sets a due time of ``now`` and the second one plans. Nothing about what gets planned, what ids the
blocks carry, or what revisions are appended differs from what the container does on its own
schedule, and that matters more here than anywhere else in the harness: a block id a test wrote
itself would prove neither half of the round trip a recording makes.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from typing import Final

from syncr_api.core.clock import utc_now
from syncr_api.horizon.runner import PlanHorizonRunner
from syncr_api.worker.main import build_context, run_forever
from syncr_common.logging import configure_logging

# Two, and both are needed: the first sets the runner's due time and the second is the one that
# is due. This mirrors the container, where every tick after the first is a tick that can plan.
ITERATIONS: Final = 2

EXIT_OK: Final = 0


async def run() -> int:
    """Run the maintainer's two duties once against every tenant in the database."""
    context = build_context()
    configure_logging(
        environment=context.settings.environment, log_level=context.settings.log_level
    )
    runner = PlanHorizonRunner(interval=timedelta(0), clock=utc_now)
    try:
        await run_forever(
            context,
            runners=(runner,),
            tick_seconds=0,
            max_iterations=ITERATIONS,
        )
    finally:
        await context.database.engine.dispose()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
