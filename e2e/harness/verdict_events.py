#!/usr/bin/env python3
"""Print the verdict-event rows and the early-catch ratio the product computes from them.

Run as a one-shot in the api image::

    docker compose -f docker-compose.yml -f e2e/docker-compose.e2e.yml \\
      run --rm --no-deps worker python /harness/verdict_events.py

WHY A ONE-SHOT AND NOT A ROUTE. S35's observations are "exactly two episodes" and "a ratio of
exactly 0.5", and neither is on the wire: ``VerdictEvent`` rows are an observability record rather
than a product surface, and the ratio is a Prometheus gauge the worker's own registry serves on a
port reachable only inside ``app-net`` -- deliberately, because proxying ``/metrics`` would publish
every figure about the user's plan through the tunnel.

So the observation is taken where the figure lives, through the product's OWN code. The history is
read the way ``TenantProductReader._verdict_history`` reads it, full history per week touched rather
than the period's slice, because an episode's boundaries depend on the rows before the period; and
the ratio is ``caught_early_over``, which is the function the nightly job calls. A second
implementation of the episode rule is what would let this print 0.5 while the gauge published 0.33,
which is exactly the failure S35 exists to catch.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

from syncr_api.core.db import create_database
from syncr_api.core.settings import EnvSettings
from syncr_api.observability.early_catch import caught_early_over
from syncr_api.plans.verdict_events import VerdictEventRepository
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.plans.records import VerdictEventRecord
    from syncr_domain.weeks import IsoWeek

# The window the ratio is computed over. Wide enough to hold everything one suite run wrote and
# narrow enough that nothing else could be in it: a scratch database is minutes old.
LOOKBACK = timedelta(days=7)

TENANTS = text("SELECT id FROM tenants ORDER BY id")


async def run(database_url: str) -> int:
    """Print every row, and the ratio the product's own episode rule reads out of them."""
    database = create_database(database_url)
    now = datetime.now(UTC)
    period = Interval(now - LOOKBACK, now + timedelta(minutes=1))
    printed: list[dict[str, object]] = []
    ratios: dict[str, float | None] = {}
    try:
        async with database.sessionmaker() as session:
            tenant_ids = [row[0] for row in (await session.execute(TENANTS)).all()]
            for tenant_id in tenant_ids:
                verdicts = VerdictEventRepository(session, tenant_id)
                touched = {row.iso_week for row in await verdicts.since(period.start)}
                history: dict[IsoWeek, Sequence[VerdictEventRecord]] = {
                    iso_week: await verdicts.for_week(iso_week) for iso_week in sorted(touched)
                }
                for iso_week, recorded in history.items():
                    printed.extend(
                        {
                            "isoWeek": str(iso_week),
                            "occurredAt": row.occurred_at.isoformat(),
                            "feasible": row.feasible,
                            "provenance": row.provenance.value,
                            "surface": row.surface.value,
                            "sessionModeActive": row.session_mode_active,
                            "shortfallKinds": [kind.value for kind in row.shortfall_kinds],
                            "inputVersion": row.input_version,
                        }
                        for row in recorded
                    )
                ratios[str(tenant_id)] = caught_early_over(history, period=period)
    finally:
        await database.engine.dispose()

    json.dump({"rows": printed, "caughtEarlyByTenant": ratios}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(EnvSettings().database_url)))
