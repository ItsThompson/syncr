#!/usr/bin/env python3
"""Produce named weeks through the horizon producer without asking the solver."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from typing import Final

from syncr_api.accounts.repository import TenantRepository
from syncr_api.core.db import create_database
from syncr_api.core.settings import WORKER_SERVICE, EnvSettings, build_service_settings
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.production import WeekProducer
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_domain.weeks import IsoWeek

EXIT_OK: Final = 0


async def run(weeks: tuple[IsoWeek, ...]) -> int:
    settings = build_service_settings(service=WORKER_SERVICE, env=EnvSettings(_env_file=None))
    database = create_database(settings.database_url)
    try:
        async with database.sessionmaker() as session:
            tenant_ids = await TenantRepository(session).list_ids()
        if len(tenant_ids) != 1:
            raise RuntimeError(f"expected one seeded tenant, found {len(tenant_ids)}")

        now = datetime.now(UTC)
        async with database.sessionmaker() as session, session.begin():
            tenant_id = tenant_ids[0]
            producer = WeekProducer(
                assembler=build_week_assembler(session, tenant_id, caller=AssemblyCaller.MAINTAINER),
                revisions=PlanRepository(session, tenant_id),
                versions=WeekInputVersionRepository(session, tenant_id),
                weights=WeightSetRepository(session, tenant_id),
                operations=OperationLifecycle(OperationRepository(session, tenant_id), lambda: now),
            )
            for week in weeks:
                await producer.advance_into(week, now=now)
    finally:
        await database.engine.dispose()
    return EXIT_OK


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("supply at least one ISO week")
    supplied_weeks = tuple(IsoWeek.parse(value) for value in sys.argv[1:])
    raise SystemExit(asyncio.run(run(supplied_weeks)))
