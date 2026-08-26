"""What both maintainer suites declare before a tick: a clock and a write target.

The plan horizon maintainer has two duties and a suite each, and both drive the real runner against
a real Postgres. So the declarations they share live here rather than in either suite: duty 2 probes
exactly the weeks duty 1 resolved. The tenant minimum both suites declare lives in
:mod:`tests.live_minimums`, alongside the one copy every driver suite shares.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from syncr_domain.identifiers import TenantId

LONDON = "Europe/London"
AUCKLAND = "Pacific/Auckland"

# Monday of 2026-W07, mid-morning in London, so a fortnight's horizon covers W07 and W08 and the
# week list is the two-week case rather than the three-week one.
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

# Sunday of the same week at 22:00, where February in London is UTC. The week's span ends at the
# following Monday's local midnight, so two hours of capacity are left and the Area's three-hour
# floor cannot be reached: the week is impossible and nothing but the clock made it so.
LATE_IN_THE_WEEK = datetime(2026, 2, 15, 22, 0, tzinfo=UTC)
CAPACITY_LEFT_MINUTES = 120

LAST_WEEK = IsoWeek(2026, 6)
THIS_WEEK = IsoWeek(2026, 7)
NEXT_WEEK = IsoWeek(2026, 8)
THIRD_WEEK = IsoWeek(2026, 9)


class Ticking:
    """A clock that advances a millisecond per read, as a real one does.

    Three assertions rest on that. Every operation one pass creates takes a distinct
    ``scheduled_for``, so the order the weeks were planned in is readable from the rows. Every
    revision one pass appends carries the SAME ``created_at``, because the pass reads the clock once
    and passes that instant down. And every verdict transition one tick records carries the same
    ``occurred_at`` for the same reason: one tick, one instant.
    """

    STEP = timedelta(milliseconds=1)

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        read = self.at
        self.at += self.STEP
        return read

    def advance(self, by: timedelta) -> None:
        self.at += by


async def declare_a_write_target(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, horizon_days: int
) -> None:
    """A projection target with a stated horizon, which is what decides how many weeks are kept."""
    async with sessions() as session, session.begin():
        sources = CalendarSourceRepository(session, tenant_id)
        target = await sources.create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="Phone",
            external_id="https://example.test/plan.ics",
            included=True,
            horizon_days=None,
            created_at=NOW,
        )
        await sources.designate_write_target(target.id, horizon_days=horizon_days)
