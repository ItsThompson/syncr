"""How a caller acquires a week assembler, and which reader each seam is wired to.

The assembler takes sixteen collaborators, so composing one is stated here rather than at each
call site: three components assemble a week and a second copy of this list is how one of them
would come to read a different set of tables.

Every repository is scoped to a tenant HERE, before the assembler exists, so no statement it
composes can reach another tenant's rows. The tenant is a parameter rather than a request-scoped
dependency, because two of the three callers are not requests: the worker solves a week and the
horizon maintainer materializes one, and neither has a principal.

Two seams are wired to readers that answer with nothing, and each is the honest reading of this
deployment rather than a placeholder:

``NoPlacements`` for the live plan and the pins, because no code names the keys a stored block or
a stored pin binding holds, so no committed capacity can be read back out of a document.

``NoRecordedOutcomes`` for the habit outcome log, for the same reason one module over: nothing
writes a binding onto an outcome, so no row can be attributed to a habit occurrence.

Whoever brings either online changes one line here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.areas.repository import AreaRepository
from syncr_api.habits.outcome_log import NoRecordedOutcomes
from syncr_api.habits.repository import HabitRepository
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller, WeekAssembler
from syncr_api.plans.placements import NoPlacements
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.preferences.repository import PreferenceRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.repository import TemplateRepository, WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


def build_week_assembler(
    transaction: AsyncSession, tenant_id: TenantId, *, caller: AssemblyCaller
) -> WeekAssembler:
    """One assembler, scoped to ``tenant_id``, labelled by the caller that will ask it.

    ``caller`` is bound at construction rather than passed per call, because the method's three
    arguments are the week, the instant, and the concession being evaluated: a fourth naming who
    is asking would put a metric label in the contract every consumer has to satisfy. The wiring
    is where the answer is already known.
    """
    return WeekAssembler(
        settings=SettingsRepository(transaction, tenant_id),
        overrides=TravelOverrideRepository(transaction, tenant_id),
        routines=RoutineRepository(transaction, tenant_id),
        week_pattern=WeekPatternRepository(transaction, tenant_id),
        templates=TemplateRepository(transaction, tenant_id),
        habits=HabitRepository(transaction, tenant_id),
        outcomes=NoRecordedOutcomes(),
        tasks=TaskRepository(transaction, tenant_id),
        areas=AreaRepository(transaction, tenant_id),
        preferences=PreferenceRepository(transaction, tenant_id),
        off_plan=OffPlanPeriodRepository(transaction, tenant_id),
        placements=NoPlacements(),
        adjustments=WeekAdjustmentRepository(transaction, tenant_id),
        weights=WeightSetRepository(transaction, tenant_id),
        versions=WeekInputVersionRepository(transaction, tenant_id),
        revisions=PlanRepository(transaction, tenant_id),
        caller=caller,
    )
