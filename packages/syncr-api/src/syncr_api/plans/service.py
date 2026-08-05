"""``WeekService``: the Week screen's whole read, its history, and the request to solve it.

Four methods, and the first is why this endpoint exists at all: composing the week from six separate
routes would make the one screen a user lives in the one place where a chatty API is visibly slow.

## The read writes nothing, and that is structural rather than remembered

It appends no revision, creates no operation, bumps no version, and appends no ``VerdictEvent``.
Every collaborator below is either a reader or, in the budget's case, a service whose own read is
stated to write nothing. Navigating between weeks with ``[`` and ``]`` is not a mutation, so a week
fifty weeks out has no plan and says why instead of quietly queueing work.

## ``live`` is nullable, and the reason is carried beside it

A week the plan horizon maintainer has not reached has no plan. The alternatives were a read that
queues work and a fabricated empty document, and both are worse than a null with a stated reason.
Which reason, and the facts the screen's two actions need, is ``emptiness.py``.

## The three figures on the strip are the budget report's, not the document's

``readings`` is composed from the same ``BudgetService.read`` the pie review divides, so a figure on
the strip cannot disagree with the same figure in the review: they are one arithmetic over one
occupancy read, not two implementations that agree today. The document's own three figures are as of
the instant it was produced and are deliberately absent from the wire.

## Three costs are accepted here rather than pushed onto a collaborator

**The off-plan periods are read twice**, once as intervals inside the budget's denominator and once
as records for the screen's gutter. They are two shapes of one small indexed read, and a reader
answering with both would put the screen's fields on the budget's occupancy protocol.

**The week is parsed before the budget is asked**, which parses it again. That is what makes a
malformed identifier a 422 naming the path parameter the caller sent rather than the budget's own
query parameter.

**A week with no plan costs two extra reads**, the minimum inputs, and neither is on the path a week
WITH a plan takes. The home zone the horizon is resolved in is not among them: it rides on the
budget's view beside the zones, from the one read of the profile that both come from.

## ``operation`` reports either plan operation, not only a solve

A materialize in flight changes the same thing a solve changes, and the field exists so a client
knows what to follow and when to read the week again. Reporting the solve alone would leave a client
polling nothing while the maintainer produced the plan it is waiting for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.calendars.horizons import read_horizon_days
from syncr_api.concessions.config import ISO_WEEK_FIELD
from syncr_api.core.errors import Conflict
from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.plans.currency import plan_currency
from syncr_api.plans.emptiness import Horizon, empty_week
from syncr_api.plans.readings import week_readings
from syncr_api.plans.stored_documents import plan_document
from syncr_api.plans.week_config import HISTORY_PAGE
from syncr_api.plans.week_views import WeekRevisions, WeekView
from syncr_api.solving.config import PLAN_KINDS, SOLVE
from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.budgets.service import BudgetService, BudgetView
    from syncr_api.calendars.repository import CalendarSourceRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_api.plans.confirmations import DayConfirmationReader
    from syncr_api.plans.emptiness import EmptyWeek
    from syncr_api.plans.readiness import MinimumInputs
    from syncr_api.plans.readings import WeekReadings
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.weeks")

# What the week view reports when nothing has referenced the week yet. Versions start at one, so
# zero is a value no row can hold and reads as "untracked" rather than as a version.
UNTRACKED_VERSION = 0


class WeekService:
    """Reads one tenant's week, its history, and asks for a plan when one is wanted."""

    def __init__(
        self,
        *,
        budgets: BudgetService,
        revisions: PlanRepository,
        versions: WeekInputVersionRepository,
        operations: OperationRepository,
        lifecycle: OperationLifecycle,
        minimum: MinimumInputs,
        sources: CalendarSourceRepository,
        off_plan: OffPlanPeriodRepository,
        confirmations: DayConfirmationReader,
        clock: Clock,
    ) -> None:
        self._budgets = budgets
        self._revisions = revisions
        self._versions = versions
        self._operations = operations
        self._lifecycle = lifecycle
        self._minimum = minimum
        self._sources = sources
        self._off_plan = off_plan
        self._confirmations = confirmations
        self._clock = clock

    @measured("weeks")
    async def read(self, principal: Principal, iso_week: str) -> WeekView:
        """The whole week, in one read that writes nothing.

        ``now`` is read once and passed to everything below it, which is the discipline the horizon
        maintainer states: a tick that read the clock per collaborator could compute a horizon from
        one date and a per-day figure from another, and at local midnight the two would differ by a
        day. Today the two consumers of it are on opposite branches, so at most one reads it per
        request and the invariant is cheap rather than load-bearing.
        """
        require_scope(principal, Scope.PLAN_READ)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        now = self._clock()
        budget = await self._budgets.read(principal, str(week))
        live = await self._revisions.latest(week)
        document = None if live is None else plan_document(live.document)
        in_flight = await self._operations.in_flight_of(week, kinds=PLAN_KINDS)
        return WeekView(
            iso_week=week,
            span=budget.span,
            zone_by_date=budget.zone_by_date,
            live=document,
            empty=None if document is not None else await self._why_empty(week, budget, now=now),
            off_plan=await self._off_plan.for_span(budget.span),
            operation=in_flight,
            input_version=await self._tracked_version(week),
            readings=(
                None
                if document is None
                else await self._readings(document, budget=budget, in_flight=in_flight, now=now)
            ),
        )

    async def _tracked_version(self, week: IsoWeek) -> int:
        """The week's input version, or the value no row can hold when nothing has referenced it."""
        current = await self._versions.current(week)
        return UNTRACKED_VERSION if current is None else current

    @measured("weeks")
    async def revisions(self, principal: Principal, iso_week: str) -> WeekRevisions:
        """One page of a week's revision history, newest first. Read-only, like the table it reads.

        One row more than the page is asked for and dropped, so the truncation is measured rather
        than guessed: a page exactly as long as its bound is indistinguishable from a truncated one
        without it.
        """
        require_scope(principal, Scope.PLAN_READ)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        found = await self._revisions.history(week, limit=HISTORY_PAGE + 1)
        return WeekRevisions(revisions=found[:HISTORY_PAGE], truncated=len(found) > HISTORY_PAGE)

    @measured("weeks")
    async def verdict(self, principal: Principal, iso_week: str) -> None:
        """The week's verdict alone, for a cheap refresh. Always ``None``, and writes nothing.

        The identifier is still parsed, so a malformed week is refused rather than answered with a
        null that reads as "this week has no verdict". Ticket 44 computes the verdict here, and it
        appends no ``VerdictEvent`` when it does: a read is deliberately absent from the surfaces a
        transition may be recorded from.
        """
        require_scope(principal, Scope.PLAN_READ)
        require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)

    @measured("weeks")
    async def request_solve(
        self, principal: Principal, iso_week: str, *, immediate: bool
    ) -> OperationRecord:
        """Ask for a plan for ``iso_week``, and answer with the operation to follow.

        **Idempotent per week, with no key**, because at most one non-terminal solve for a week can
        exist: a second request while one is in flight answers with the one already running rather
        than creating a rival. The database's partial unique index is what makes that an invariant
        rather than a race this read narrows.

        Ticket 40 owns the debounce window and the coalescing, so ``immediate`` is recorded here and
        has nothing yet to bypass: every request is due now, which is what the coordinator's own
        immediate path will mean.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        readiness = await self._minimum.read()
        if not readiness.is_ready:
            raise Conflict(
                f"{week} cannot be solved yet, because syncr still needs {readiness.statement()}. "
                "Nothing was changed, and no plan was invented: declare what is missing and ask "
                "again, or wait and this week is planned without you asking."
            )
        in_flight = await self._operations.in_flight(week, kind=SOLVE)
        if in_flight is not None:
            _log.info(
                "weeks.solve.joined",
                tenant_id=str(principal.tenant_id),
                iso_week=str(week),
                operation_id=str(in_flight.id),
                status=in_flight.status,
            )
            return in_flight
        requested = await self._lifecycle.enqueue(kind=SOLVE, iso_week=week)
        _log.info(
            "weeks.solve.requested",
            tenant_id=str(principal.tenant_id),
            iso_week=str(week),
            operation_id=str(requested.id),
            immediate=immediate,
        )
        return requested

    async def _readings(
        self,
        document: PlanDocument,
        *,
        budget: BudgetView,
        in_flight: OperationRecord | None,
        now: datetime,
    ) -> WeekReadings:
        """The strip's figures for a week that holds a plan.

        The in-flight operation is passed in rather than read again: the view reports the same row,
        and two reads of it could straddle a worker's claim and report a plan as current while the
        row beside it said it was being recomputed.
        """
        return week_readings(
            document,
            span=budget.span,
            report=budget.report,
            off_plan=budget.off_plan,
            confirmed=await self._confirmations.confirmed_dates(document.iso_week),
            now=now,
            currency=plan_currency(
                in_flight=in_flight,
                latest=await self._operations.latest_of(document.iso_week, kinds=PLAN_KINDS),
            ),
        )

    async def _why_empty(self, week: IsoWeek, budget: BudgetView, *, now: datetime) -> EmptyWeek:
        """Why this week holds no plan, read only on the path where it holds none.

        The horizon is the maintainer's own derivation over the write target's own length, so the
        week this route calls beyond the horizon is exactly the week the maintainer skips. The zone
        the local date is resolved in is the budget's own, from the one read of the profile the span
        came from: a second read of the settings row here would be a second answer to which date
        this tenant is on.
        """
        return empty_week(
            week,
            readiness=await self._minimum.read(),
            horizon=Horizon.of(
                today=local_date(now, budget.home_zone),
                days=await read_horizon_days(self._sources),
            ),
        )
