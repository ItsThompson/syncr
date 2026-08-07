"""Composition for the product-metric reader: the one place its collaborators are chosen.

Separate from both the reader and the job, for the reason every feature package keeps its wiring
apart: the reader states what it needs and the job states what it publishes, and neither should hold
the list of repositories a deployment builds them from. A test substitutes a collaborator by calling
the reader's constructor directly.

The zone profile is resolved here rather than inside the reader, because a week's boundaries are the
user's own and resolving them needs two more reads that have nothing to do with a product metric.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.observability.config import MEASUREMENT_WEEKS, STREAK_LOOKBACK_WEEKS
from syncr_api.observability.readings import TenantProductReader
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.outcomes.confirmations import RecordedDayConfirmations
from syncr_api.outcomes.planned_days import PlannedDayReader
from syncr_api.plans.edits import EditEventRepository
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.verdict_events import VerdictEventRepository
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.zone_reading import as_domain, zone_profile

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


async def build_product_reader(session: AsyncSession, tenant_id: TenantId) -> TenantProductReader:
    """The reader for one tenant, over repositories scoped to it."""
    settings = SettingsRepository(session, tenant_id)
    overrides = TravelOverrideRepository(session, tenant_id)
    plans = PlanRepository(session, tenant_id)
    outcomes = BlockOutcomeRepository(session, tenant_id)
    return TenantProductReader(
        outcomes=outcomes,
        plans=plans,
        verdicts=VerdictEventRepository(session, tenant_id),
        edits=EditEventRepository(session, tenant_id),
        off_plan=OffPlanPeriodRepository(session, tenant_id),
        confirmations=RecordedDayConfirmations(
            PlannedDayReader(plans), outcomes, settings, overrides
        ),
        profile=zone_profile(
            (await settings.read()).home_zone, as_domain(await overrides.list_all())
        ),
        measurement_weeks=MEASUREMENT_WEEKS,
        streak_lookback_weeks=STREAK_LOOKBACK_WEEKS,
    )
