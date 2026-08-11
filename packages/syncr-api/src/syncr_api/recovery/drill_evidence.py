"""The order the drill's evidence is written in, which is the order its writes depend on each other.

A week has to hold a plan before a solve can fill it, hold a filled slot before an outcome can be
recorded against one, and hold a confirmed completion before a restore has a cursor to re-derive.
So the sequence is the design here, and it is separate from the console script for one reason: what
a test drives is this, against a database, while the script's own part is deciding whether it may
write at all and provisioning the tenant it writes as.

Every step is its own transaction, because two of them are not statements at all: a solve runs
through the worker's duty, which opens sessions of its own, and the bootstrap command runs in a
process of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.recovery import drill_history as history
from syncr_api.recovery.drill_declarations import declare

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.principal import Principal
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import HabitId
    from syncr_domain.plan import Block
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True)
class Written:
    """What one run did, in the terms the next reader of the database asks about.

    A run that found everything already in place reports the same week with nothing planned, nothing
    solved and nothing pinned, which is what makes a repeat visible as a repeat rather than as a
    second seed.
    """

    iso_week: IsoWeek
    materialized: bool
    solved: bool
    adopted: bool
    placed: int
    recorded: int
    confirmed: int
    pinned: bool


async def write_the_evidence(
    context: WorkerContext, principal: Principal, *, now: datetime
) -> Written:
    """Declare, plan, solve, record, confirm, pin and concede, in that order."""
    database = context.database
    week = history.the_week_behind(now)

    async with database.sessionmaker() as session, session.begin():
        declarations = await declare(session, principal)

    async with database.sessionmaker() as session, session.begin():
        materialized = await history.materialize(session, principal.tenant_id, week)

    async with database.sessionmaker() as session:
        occurrences = await _occurrences(session, principal, week, declarations.habit_id)
        solve = await history.the_weeks_solve(session, principal.tenant_id, week)

    # Two reasons to ask for one, and neither is "every run asks": a week holding no occurrence has
    # nothing to record an outcome against, and a concession names the solve that caused it, so one
    # has to exist to be named. A solve appends a revision, which is why a run that needs neither
    # asks for none.
    solved = False
    adopted = False
    if not occurrences or solve is None:
        solved = True
        async with database.sessionmaker() as session, session.begin():
            solve = await history.request_a_solve(session, principal, week)
        await history.run_the_solve(context, week)
        async with database.sessionmaker() as session, session.begin():
            adopted = await history.adopt_a_proposal(session, principal, week)
        async with database.sessionmaker() as session:
            occurrences = await _occurrences(session, principal, week, declarations.habit_id)

    async with database.sessionmaker() as session, session.begin():
        recorded = await history.record_what_happened(session, principal, week, occurrences)
    async with database.sessionmaker() as session, session.begin():
        confirmed = await history.confirm_the_days(session, principal, occurrences[: len(recorded)])

    async with database.sessionmaker() as session, session.begin():
        pinned = not await history.already_pinned(session, principal.tenant_id, week)
        if pinned:
            await history.hold_a_pin(session, principal, week, occurrences[-1])

    async with database.sessionmaker() as session, session.begin():
        await history.concede_a_floor_breach(
            session,
            principal.tenant_id,
            week,
            area_id=declarations.area_id,
            operation_id=solve.id,
        )

    return Written(
        iso_week=week.iso_week,
        materialized=materialized,
        solved=solved,
        adopted=adopted,
        placed=len(occurrences),
        recorded=len(recorded),
        confirmed=confirmed,
        pinned=pinned,
    )


async def _occurrences(
    session: AsyncSession, principal: Principal, week: history.DrillWeek, habit_id: HabitId
) -> tuple[Block, ...]:
    """Every occurrence of the drill's habit the week's plan of record places."""
    document = await history.live_plan(session, principal.tenant_id, week)
    return () if document is None else history.occurrences_of(document, habit_id)
