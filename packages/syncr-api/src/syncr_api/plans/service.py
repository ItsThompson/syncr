"""``WeekService``: the Week screen's whole read, its history, its verdict, its proposal, its solve.

Five methods, and the first is why this endpoint exists at all: composing the week from ten separate
routes would make the one screen a user lives in the one place where a chatty API is visibly slow.

## Every read here writes nothing, and that is structural rather than remembered

No revision, no operation, no version bump, and no ``VerdictEvent``. Every collaborator below is
either a reader or, in the budget's case, a service whose own read is stated to write nothing.
Navigating between weeks with ``[`` and ``]`` is not a mutation, so a week fifty weeks out has no
plan and says why instead of quietly queueing work.

**That includes the verdict, which four of the five reads now compute.** ``VE6`` forbids a read from
appending a transition, and ``VE8`` is the same argument from the metric's side: a transition a read
observes is recorded by the next mutation or by the maintainer's next tick.

## ``live`` is nullable, and the reason is carried beside it

A week the plan horizon maintainer has not reached has no plan. The alternatives were a read that
queues work and a fabricated empty document, and both are worse than a null with a stated reason.
Which reason, and the facts the screen's two actions need, is ``emptiness.py``.

## ``verdict`` is null exactly when ``live`` is, and which verdict it is, is a rule

A week with no plan has had nothing computed about it, so a verdict beside it would be a claim about
nothing. Which of two verdicts a week WITH a plan serves is ``served_verdicts.py``, and it is the
one rule that lets a packing failure survive a read at all.

## The three figures on the strip are the budget report's, not the document's

``readings`` is composed from the same ``BudgetService.read`` the pie review divides, so a figure on
the strip cannot disagree with the same figure in the review: they are one arithmetic over one
occupancy read, not two implementations that agree today. The document's own three figures are as of
the instant it was produced and are deliberately absent from the wire.

**One figure is on this payload twice today and the two disagree**, and it is not this module's to
fix: ``readings.discretionaryMinutes`` is the budget's, whose occupancy reader fills one of four
subtrahends, and ``verdict.discretionaryMinutes`` is the probe's, which subtracts all four. Ticket
1310 owns the seam that closes it, and both figures move when it lands because the week service
acquires the budget service rather than recomputing its arithmetic.

## Four costs are accepted here rather than pushed onto a collaborator

**The off-plan periods are read twice**, once as intervals inside the budget's denominator and once
as records for the screen's gutter. They are two shapes of one small indexed read, and a reader
answering with both would put the screen's fields on the budget's occupancy protocol.

**The week is parsed before the budget is asked**, which parses it again. That is what makes a
malformed identifier a 422 naming the path parameter the caller sent rather than the budget's own
query parameter.

**A week with no plan costs two extra reads**, the minimum inputs, and neither is on the path a week
WITH a plan takes. The home zone the horizon is resolved in is not among them: it rides on the
budget's view beside the zones, from the one read of the profile that both come from.

**A week whose pending slot is empty or stale costs a whole assembly**, which is the dominant cost
of this read when it is paid. It is what a live verdict is computed from, and the alternative is a
verdict field that is null on every week between an approval and the next solve.

## ``operation`` reports either plan operation, not only a solve

A materialize in flight changes the same thing a solve changes, and the field exists so a client
knows what to follow and when to read the week again. Reporting the solve alone would leave a client
polling nothing while the maintainer produced the plan it is waiting for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.calendars.horizons import read_horizon_days
from syncr_api.concessions.config import ISO_WEEK_FIELD
from syncr_api.core.errors import Conflict, NotFound
from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.plans.candidates import awaiting_approval
from syncr_api.plans.currency import plan_currency
from syncr_api.plans.emptiness import Horizon, empty_week
from syncr_api.plans.history import revision_page
from syncr_api.plans.pending_reads import pending_proposal
from syncr_api.plans.readings import week_readings
from syncr_api.plans.stored_documents import plan_document
from syncr_api.plans.stored_proposals import read_proposal_diff
from syncr_api.plans.week_config import HISTORY_PAGE, WEEK_RESOURCE
from syncr_api.plans.week_views import PendingProposal, WeekRevisions, WeekView
from syncr_api.solving.config import PLAN_KINDS
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
    from syncr_api.plans.adjustments import WeekAdjustmentRepository
    from syncr_api.plans.confirmations import DayConfirmationReader
    from syncr_api.plans.conflicts import PlanConflictRepository
    from syncr_api.plans.emptiness import EmptyWeek
    from syncr_api.plans.pins import PinRepository
    from syncr_api.plans.proposals import PendingProposalRepository
    from syncr_api.plans.readiness import MinimumInputs
    from syncr_api.plans.readings import WeekReadings
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.served_verdicts import ServedVerdict
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository
    from syncr_domain.feasibility import Verdict
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.weeks")


class WeekService:
    """Reads one tenant's week, its history, and asks for a plan when one is wanted."""

    def __init__(
        self,
        *,
        budgets: BudgetService,
        revisions: PlanRepository,
        adjustments: WeekAdjustmentRepository,
        proposals: PendingProposalRepository,
        pins: PinRepository,
        conflicts: PlanConflictRepository,
        verdicts: ServedVerdict,
        versions: WeekInputVersionRepository,
        operations: OperationRepository,
        coordinator: SolveCoordinator,
        minimum: MinimumInputs,
        sources: CalendarSourceRepository,
        off_plan: OffPlanPeriodRepository,
        confirmations: DayConfirmationReader,
        clock: Clock,
    ) -> None:
        self._budgets = budgets
        self._revisions = revisions
        self._adjustments = adjustments
        self._proposals = proposals
        self._pins = pins
        self._conflicts = conflicts
        self._verdicts = verdicts
        self._versions = versions
        self._operations = operations
        self._coordinator = coordinator
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
        day. Three consumers read it now, the horizon, the per-day figures and the assembly a live
        verdict is computed from, and the verdict's own instant is stamped from it, so a client
        comparing the verdict's instant with the week beside it reads one instant rather than two.

        The version is read once and used twice, as the figure the view reports and as the currency
        test the served verdict applies to the pending slot. **The slot is read once for the same
        reason**, and its read is ordered LAST of the three that an approval touches. Two statements
        reading the slot would take two snapshots under ``READ COMMITTED``, and an approval landing
        between them would answer with a proposal beside a verdict computed as though there were
        none. Reading the concessions BEFORE it is the other half: an approval landing between those
        two leaves its concession absent from this answer rather than present twice, once awaiting
        assent and once granted under the one identifier both name.
        """
        require_scope(principal, Scope.PLAN_READ)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        now = self._clock()
        budget = await self._budgets.read(principal, str(week))
        live = await self._revisions.latest(week)
        document = None if live is None else plan_document(live.document)
        in_flight = await self._operations.in_flight_of(week, kinds=PLAN_KINDS)
        version = await self._versions.tracked_version(week)
        adjustments = await self._adjustments.for_week(week)
        held = await self._proposals.find(week)
        return WeekView(
            iso_week=week,
            span=budget.span,
            zone_by_date=budget.zone_by_date,
            live=document,
            empty=None if document is not None else await self._why_empty(week, budget, now=now),
            proposal=None if held is None else read_proposal_diff(held.proposal_diff, week),
            candidate_adjustment=None if held is None else awaiting_approval(held),
            adjustments=adjustments,
            pins=await self._pins.for_week(week),
            conflicts=await self._conflicts.for_week(week),
            off_plan=await self._off_plan.for_span(budget.span),
            verdict=(
                None
                if document is None
                else await self._verdicts.for_week(week, now=now, input_version=version, held=held)
            ),
            operation=in_flight,
            input_version=version,
            readings=(
                None
                if document is None
                else await self._readings(document, budget=budget, in_flight=in_flight, now=now)
            ),
        )

    @measured("weeks")
    async def revisions(self, principal: Principal, iso_week: str) -> WeekRevisions:
        """One page of a week's revision history, newest first. Read-only, like the table it reads.

        One row more than the page is asked for and used twice, so neither answer is guessed: it is
        what makes the truncation measured, because a page exactly as long as its bound is
        indistinguishable from a truncated one without it, and it is the plan the oldest row on the
        page changed, which is what lets that row say what it auto-applied.

        The week's concessions are read once for the whole page rather than per revision. A document
        names the ones it was solved under by identifier, and one read answers every row.
        """
        require_scope(principal, Scope.PLAN_READ)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        return revision_page(
            await self._revisions.history(week, limit=HISTORY_PAGE + 1),
            held=await self._adjustments.for_week(week),
            page=HISTORY_PAGE,
        )

    @measured("weeks")
    async def verdict(self, principal: Principal, iso_week: str) -> Verdict | None:
        """The week's verdict alone, for a cheap refresh. Writes nothing.

        The same rule the composed read serves, so the cheap refresh and the whole read cannot
        report different provenance for one week: the slot's verdict while its input version is
        current, and a live probe otherwise.

        ``None`` exactly when the week holds no plan, which is the same biconditional the view
        states: nothing has been computed about such a week, and a verdict about a plan that does
        not exist would be a claim about nothing.

        It appends no ``VerdictEvent`` on either branch. ``VE6``: a read is deliberately absent from
        the surfaces a transition may be recorded from, and ``VE8`` is the other half of the same
        argument -- a fresh probe here would flip provenance back from ``solver`` after every solve.
        """
        require_scope(principal, Scope.PLAN_READ)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        if await self._revisions.latest(week) is None:
            return None
        return await self._verdicts.for_week(
            week,
            now=self._clock(),
            input_version=await self._versions.tracked_version(week),
            held=await self._proposals.find(week),
        )

    @measured("weeks")
    async def proposal(self, principal: Principal, iso_week: str) -> PendingProposal:
        """The proposal this week is holding, or a 404 because its slot is empty.

        A 404 rather than a null body: the slot is a resource with at most one occupant, so an empty
        one is an absent resource. A null would have to be told apart from a proposal that proposes
        nothing, and the diff's own emptiness already means that.

        The stored diff and the stored verdict are both rebuilt through the domain's own
        constructors, so a corrupt row is refused here rather than rendered.
        """
        require_scope(principal, Scope.PLAN_READ)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        held = await self._proposals.find(week)
        if held is None:
            raise NotFound(
                f"That {WEEK_RESOURCE} is proposing nothing: its plan of record is what it holds, "
                "and there is nothing awaiting your assent."
            )
        return pending_proposal(held)

    @measured("weeks")
    async def request_solve(
        self, principal: Principal, iso_week: str, *, immediate: bool
    ) -> OperationRecord:
        """Ask for a plan for ``iso_week``, and answer with the operation to follow.

        **Idempotent per week, with no key**, because at most one non-terminal solve for a week can
        exist: a second request while one is in flight answers with the one already running rather
        than creating a rival. The database's partial unique index is what makes that an invariant
        rather than a race a read narrows.

        The re-solve control is ``immediate``, which is what bypassing the debounce window means: a
        request from a person is not being coalesced with anything, so it is due now rather than at
        the end of a window an earlier mutation opened.
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
        # This control changes no input, so the version it reports is the one the week already
        # holds: it is what the client's response says was acknowledged, and it is not the guard.
        return await self._coordinator.request_solve(
            week, await self._versions.tracked_version(week), immediate=immediate
        )

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
