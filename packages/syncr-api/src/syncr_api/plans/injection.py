"""How a caller acquires a week assembler and a week service, and which reader each seam is wired
to.

The assembler takes nineteen collaborators, so composing one is stated here rather than at each
call site: three components assemble a week and a second copy of this list is how one of them
would come to read a different set of tables.

Every repository is scoped to a tenant HERE, before either is built, so no statement they compose
can reach another tenant's rows. For the assembler the tenant is a parameter rather than a
request-scoped dependency, because two of its three callers are not requests: the worker solves a
week and the horizon maintainer materializes one, and neither has a principal. The week service is
request-only and takes the principal's own dependency.

**No seam here answers with nothing.** Every collaborator the assembler takes reads the tables its
own module owns, and the ones whose names invite the question say so below.

``HabitOutcomeLog`` is plan storage's projection of ``block_outcomes``, and it is the SAME reader
the habit routes acquire. One log, so the variant a plan places for a rotation habit and the variant
that habit's own screen names come from one reading rather than from two that may disagree.

``StoredPlacements`` is NOT a stub: it reads the newest revision, the week's pins, the outcomes of
the span, and the profile a pin's creation instant is dated in. Four statements behind one
collaborator call, which the seam's own module states, because the assembly's read figure counts the
call.

The week view's day confirmations are NOT a stub either: ``RecordedDayConfirmations`` reads the plan
of record and the outcome log, so the count on the Week screen and the count on the Today surface
come from one rule. Both surfaces would otherwise answer the same question about the same week.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

# FastAPI resolves these annotations at RUNTIME to build the dependency graph, and both names are
# only reachable from an annotation, so under TYPE_CHECKING they would resolve to a NameError while
# the app is being constructed.
from syncr_api.accounts.injection import ClientPrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.budgets.injection import build_budget_service
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.core.session_mode import SessionModeDep  # noqa: TC001
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS
from syncr_api.habits.repository import HabitRepository
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.outcomes.confirmations import RecordedDayConfirmations
from syncr_api.outcomes.planned_days import PlannedDayReader
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller, WeekAssembler
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.habit_log import HabitOutcomeLog
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.placements import StoredPlacements
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.readiness import MinimumInputs
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.recording import VerdictRecorder
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.served_verdicts import CurrentWeekVerdict, ServedVerdict
from syncr_api.plans.service import WeekService
from syncr_api.plans.verdict_events import VerdictEventRepository
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.preferences.repository import PreferenceRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.solving.injection import (
    build_solve_coordinator,
    configured_debounce,
    debounce_window,
)
from syncr_api.solving.repository import OperationRepository
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.repository import (
    DayTypeRepository,
    TemplateRepository,
    WeekPatternRepository,
)
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.plans.surfaces import VerdictSurface
    from syncr_domain.identifiers import TenantId

# The window a caller that states none gets: the documented default, which is also what the
# environment variable defaults to, so the two cannot be different figures.
DEFAULT_DEBOUNCE = debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS)


def build_week_assembler(
    transaction: AsyncSession, tenant_id: TenantId, *, caller: AssemblyCaller
) -> WeekAssembler:
    """One assembler, scoped to ``tenant_id``, labelled by the caller that will ask it.

    ``caller`` is bound at construction rather than passed per call, because the method's three
    arguments are the week, the instant, and the concession being evaluated: a fourth naming who
    is asking would put a metric label in the contract every consumer has to satisfy. The wiring
    is where the answer is already known.

    The anchor repositories are the calendar half's, and they are read-only here: an assembly of a
    week reads what a sync already reconciled and never writes an imported fact.
    """
    settings = SettingsRepository(transaction, tenant_id)
    return WeekAssembler(
        settings=settings,
        overrides=TravelOverrideRepository(transaction, tenant_id),
        routines=RoutineRepository(transaction, tenant_id),
        week_pattern=WeekPatternRepository(transaction, tenant_id),
        templates=TemplateRepository(transaction, tenant_id),
        day_types=DayTypeRepository(transaction, tenant_id),
        habits=HabitRepository(transaction, tenant_id),
        outcomes=HabitOutcomeLog(transaction, tenant_id),
        tasks=TaskRepository(transaction, tenant_id),
        areas=AreaRepository(transaction, tenant_id),
        preferences=PreferenceRepository(transaction, tenant_id),
        off_plan=OffPlanPeriodRepository(transaction, tenant_id),
        placements=StoredPlacements(
            PlanRepository(transaction, tenant_id),
            PinRepository(transaction, tenant_id),
            BlockOutcomeRepository(transaction, tenant_id),
            settings,
        ),
        adjustments=WeekAdjustmentRepository(transaction, tenant_id),
        anchors=AnchorRepository(transaction, tenant_id),
        anchor_types=AnchorTypeRepository(transaction, tenant_id),
        weights=WeightSetRepository(transaction, tenant_id),
        versions=WeekInputVersionRepository(transaction, tenant_id),
        revisions=PlanRepository(transaction, tenant_id),
        caller=caller,
    )


def build_served_verdict(transaction: AsyncSession, tenant_id: TenantId) -> ServedVerdict:
    """The reader that decides which verdict a read serves, scoped to ``tenant_id``.

    The assembler and the probe both carry the ``request`` caller label, because both callers of
    this are request-path reads and the assembly histogram's alert is scoped to the interactive
    caller: a read's assembly labelled ``maintainer`` would be a request's cost hidden behind a
    background figure the alert deliberately ignores.

    It reads no slot and no version of its own. Each caller reads each once and hands both in, so a
    payload cannot carry a proposal from one snapshot beside a verdict from another.
    """
    return ServedVerdict(
        assembler=build_week_assembler(transaction, tenant_id, caller=AssemblyCaller.REQUEST),
        probe=WeekProbe(caller=ProbeCaller.REQUEST),
    )


def build_current_week_verdict(
    transaction: AsyncSession, tenant_id: TenantId, *, clock: Clock
) -> CurrentWeekVerdict:
    """The verdict of the week a tenant is living in, for the backlog's at-risk column.

    Composed here rather than in the backlog's own wiring, because it is the SAME rule the Week
    screen's read serves and the same assembler behind it: two compositions of it would be two
    answers to whether a task is at risk.

    The plan repository is what makes the two screens agree about a week with no plan, and it is why
    the backlog pays no assembly on that path.
    """
    return CurrentWeekVerdict(
        served=build_served_verdict(transaction, tenant_id),
        revisions=PlanRepository(transaction, tenant_id),
        proposals=PendingProposalRepository(transaction, tenant_id),
        versions=WeekInputVersionRepository(transaction, tenant_id),
        settings=SettingsRepository(transaction, tenant_id),
        clock=clock,
    )


def build_verdict_recorder(
    transaction: AsyncSession,
    tenant_id: TenantId,
    *,
    surface: VerdictSurface,
    session_mode_active: bool,
) -> VerdictRecorder:
    """One recorder, scoped to ``tenant_id``, bound to the surface and the session state asking.

    Both are bound here for the reason ``caller`` is bound on the assembler: the wiring is where the
    answer is already known, and a per-call argument is one a service could pass wrongly or forget.
    What that buys beyond tidiness is that the set of surfaces with a producer is the set of call
    sites of this function, which a test can read out of the source.
    """
    return VerdictRecorder(
        VerdictEventRepository(transaction, tenant_id),
        surface=surface,
        session_mode_active=session_mode_active,
    )


def get_week_service(
    request: Request,
    principal: ClientPrincipalDep,
    transaction: TransactionDep,
    session_mode: SessionModeDep,
) -> WeekService:
    """The week service, wired for this request and scoped to this tenant."""
    return build_week_service(
        transaction,
        principal.tenant_id,
        clock=utc_now,
        debounce=configured_debounce(request),
        session_mode_active=session_mode,
    )


def build_week_service(
    transaction: AsyncSession,
    tenant_id: TenantId,
    *,
    clock: Clock,
    debounce: timedelta = DEFAULT_DEBOUNCE,
    session_mode_active: bool = False,
) -> WeekService:
    """One week service, scoped to ``tenant_id``, reading time from ``clock``.

    Split from the dependency above for the same reason ``build_week_assembler`` is a function of a
    tenant: the composition is fourteen collaborators, and a caller that wants one against a stated
    instant should not have to restate all fourteen. The horizon a week is compared against and the
    days a figure is charged to both move at local midnight, so an instant is what a test of either
    must be able to fix.

    The budget service is the api's own, acquired through its dependency rather than rebuilt, so the
    three figures on the summary strip are the ones the pie review divides: a second composition of
    that arithmetic here is exactly the disagreement the composed view exists to prevent.

    The concession repository serves the HISTORY as well as the composed read: a revision names the
    concessions its plan was solved under by identifier, and one read of the week's own rows answers
    every row of the page and the view's own list.

    The served verdict carries an assembler of its own, which is the dominant cost of any read whose
    week has no current proposal. It is composed through its own builder rather than inline, because
    the backlog acquires the same rule and two compositions of it would be two answers to whether a
    week can hold its commitments.

    The operation lifecycle is the solving module's, and it is the only creation path for an
    operation: a second one here would be a second reading of the state machine.

    ``debounce`` defaults to the documented value rather than being required, and the api's own
    dependency above passes what this deployment configured. Both read one constant, so a caller
    that states nothing gets the default the environment variable also defaults to.
    """
    operations = OperationRepository(transaction, tenant_id)
    revisions = PlanRepository(transaction, tenant_id)
    settings = SettingsRepository(transaction, tenant_id)
    overrides = TravelOverrideRepository(transaction, tenant_id)
    return WeekService(
        budgets=build_budget_service(transaction, tenant_id),
        revisions=revisions,
        adjustments=WeekAdjustmentRepository(transaction, tenant_id),
        proposals=PendingProposalRepository(transaction, tenant_id),
        pins=PinRepository(transaction, tenant_id),
        conflicts=PlanConflictRepository(transaction, tenant_id),
        verdicts=build_served_verdict(transaction, tenant_id),
        versions=WeekInputVersionRepository(transaction, tenant_id),
        operations=operations,
        coordinator=build_solve_coordinator(transaction, tenant_id, clock=clock, debounce=debounce),
        minimum=MinimumInputs(
            AreaRepository(transaction, tenant_id),
            WeekPatternRepository(transaction, tenant_id),
        ),
        sources=CalendarSourceRepository(transaction, tenant_id),
        off_plan=OffPlanPeriodRepository(transaction, tenant_id),
        confirmations=RecordedDayConfirmations(
            PlannedDayReader(revisions),
            BlockOutcomeRepository(transaction, tenant_id),
            settings,
            overrides,
        ),
        clock=clock,
        session_mode_active=session_mode_active,
    )


type WeekServiceDep = Annotated[WeekService, Depends(get_week_service)]
