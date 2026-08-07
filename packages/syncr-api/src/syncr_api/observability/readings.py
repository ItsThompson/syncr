"""One tenant's product-metric reading: every row the four figures are computed from, read once.

Separated from the job that publishes them, so the arithmetic is testable without a database and the
reads are testable without asserting on a gauge. What this module holds is the reads and the two
exclusions that are properties of the DATA rather than of the arithmetic.

Every read goes through a repository that is already scoped to one tenant, so no statement here is
one a scope could be forgotten on. The day-confirmation count comes from
:class:`~syncr_api.outcomes.confirmations.RecordedDayConfirmations`, which is the same rule the Week
screen and the Today surface render, so three surfaces cannot disagree about the same week.

## The two exclusions on the estimate

An unconfirmed day is a day the user did not answer for, so an actual on it was presumed rather than
observed. An off-plan span is time the user told syncr not to plan, so a block inside one was not
being followed. Neither is evidence about estimating, and both are applied here because both are
questions about which rows exist rather than about how to average them.

## The estimate is the duration the block was PLANNED for

Not a field on the outcome, which records what happened rather than what was expected. The planned
duration lives in the plan of record the outcome was recorded against, so each named revision is
read once and its document rebuilt once, however many outcomes name it.

## The streak walks backwards and stops early

Its cost is the streak's length rather than the lookback's, because the walk ends at the first week
that is neither engaged nor skipped. That is also why the reads are per week rather than one wide
read: a user with a two-week streak pays for two weeks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.observability.engagement import WeekEngagement
from syncr_api.observability.estimate import Measurement
from syncr_api.plans.stored_documents import plan_document
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState
from syncr_domain.weeks import IsoWeek, week_span

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_api.outcomes.confirmations import RecordedDayConfirmations
    from syncr_api.plans.edits import EditedBlock, EditEventRepository
    from syncr_api.plans.reality import BlockOutcomeRepository
    from syncr_api.plans.records import BlockOutcomeRecord, PlanRevisionRecord, VerdictEventRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.verdict_events import VerdictEventRepository
    from syncr_domain.identifiers import PlanRevisionId
    from syncr_domain.plan import PlanDocument
    from syncr_domain.zones import ZoneProfile

# A placement, keyed by the derived block id, which is what a plan diff pairs on.
type PlacementsById = Mapping[str, Interval]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductReading:
    """Everything the four product metrics are computed from, for one tenant, at one instant."""

    period: Interval
    measurement_weeks: int
    estimates: tuple[Measurement, ...]
    verdict_history_by_week: Mapping[IsoWeek, Sequence[VerdictEventRecord]]
    # One pair per approved revision: the plan it replaced, and the plan the user assented to.
    approved_diffs: tuple[tuple[PlacementsById, PlacementsById], ...]
    edits: tuple[EditedBlock, ...]
    weeks_newest_first: tuple[WeekEngagement, ...]


class TenantProductReader:
    """Reads one tenant's product-metric substrate over repositories that are already scoped."""

    def __init__(
        self,
        *,
        outcomes: BlockOutcomeRepository,
        plans: PlanRepository,
        verdicts: VerdictEventRepository,
        edits: EditEventRepository,
        off_plan: OffPlanPeriodRepository,
        confirmations: RecordedDayConfirmations,
        profile: ZoneProfile,
        measurement_weeks: int,
        streak_lookback_weeks: int,
    ) -> None:
        self._outcomes = outcomes
        self._plans = plans
        self._verdicts = verdicts
        self._edits = edits
        self._off_plan = off_plan
        self._confirmations = confirmations
        self._profile = profile
        self._measurement_weeks = measurement_weeks
        self._streak_lookback_weeks = streak_lookback_weeks

    async def read(self, *, now: datetime) -> ProductReading:
        """Read every figure's substrate for the period ending at the last COMPLETE ISO week.

        The current week is excluded. A ratio over a week two days old moves every hour as the week
        fills, so a panel trended by week would show a sawtooth rather than a trend.
        """
        weeks = _complete_weeks(now, count=self._measurement_weeks, profile=self._profile)
        period = Interval(
            week_span(weeks[0], self._profile).start, week_span(weeks[-1], self._profile).end
        )
        return ProductReading(
            period=period,
            measurement_weeks=self._measurement_weeks,
            estimates=await self._estimates(period),
            verdict_history_by_week=await self._verdict_history(period),
            approved_diffs=await self._approved_diffs(period),
            edits=await self._edits.for_span(period),
            weeks_newest_first=await self._engagement(now),
        )

    async def _estimates(self, period: Interval) -> tuple[Measurement, ...]:
        """Every partial outcome in the period that is evidence about estimating."""
        recorded = [
            row
            for row in await self._outcomes.for_span(period)
            if row.state == OutcomeState.PARTIAL and row.is_confirmed
        ]
        if not recorded:
            return ()
        off_plan = tuple(one.interval for one in await self._off_plan.for_span(period))
        documents = await self._documents({row.revision_id for row in recorded})
        return tuple(
            measured
            for row in recorded
            if not _inside_any(row.occurred_at, off_plan)
            if (measured := _measured(row, documents.get(row.revision_id))) is not None
        )

    async def _documents(
        self, revision_ids: set[PlanRevisionId]
    ) -> dict[PlanRevisionId, PlanDocument]:
        """Each named revision's document, rebuilt once however many outcomes name it."""
        found: dict[PlanRevisionId, PlanDocument] = {}
        for revision_id in sorted(revision_ids, key=str):
            revision = await self._plans.find(revision_id)
            if revision is not None:
                found[revision_id] = plan_document(revision.document)
        return found

    async def _verdict_history(
        self, period: Interval
    ) -> dict[IsoWeek, Sequence[VerdictEventRecord]]:
        """Each week the period touched, with its FULL history rather than the period's slice.

        An episode's boundaries depend on the rows before the period, so a slice would read a week
        that was already infeasible as newly discovered.
        """
        touched = {row.iso_week for row in await self._verdicts.since(period.start)}
        return {iso_week: await self._verdicts.for_week(iso_week) for iso_week in sorted(touched)}

    async def _approved_diffs(
        self, period: Interval
    ) -> tuple[tuple[PlacementsById, PlacementsById], ...]:
        """The plan each approval replaced, paired with the plan it made of record.

        A revision naming no predecessor is skipped: it added everything and asked about nothing,
        which is the first plan a week ever had rather than a proposal anyone assented to.
        """
        paired = []
        for approved in await self._plans.approved_in(period):
            replaced = await self._replaced(approved)
            if replaced is not None:
                paired.append(
                    (_placements(replaced), _placements(plan_document(approved.document)))
                )
        return tuple(paired)

    async def _replaced(self, approved: PlanRevisionRecord) -> PlanDocument | None:
        if approved.supersedes_id is None:
            return None
        previous = await self._plans.find(approved.supersedes_id)
        return None if previous is None else plan_document(previous.document)

    async def _engagement(self, now: datetime) -> tuple[WeekEngagement, ...]:
        """Each complete week newest first, until one that neither counts nor is skipped."""
        walked = []
        iso_week = _last_complete_week(now, profile=self._profile)
        for _ in range(self._streak_lookback_weeks):
            week = await self._engaged(iso_week)
            walked.append(week)
            if not week.is_skipped and not week.is_engaged:
                break
            iso_week = iso_week.preceding()
        return tuple(walked)

    async def _engaged(self, iso_week: IsoWeek) -> WeekEngagement:
        span = week_span(iso_week, self._profile)
        off_plan = tuple(one.interval for one in await self._off_plan.for_span(span))
        return WeekEngagement(
            ran_a_session=any(
                row.session_mode_active for row in await self._verdicts.for_week(iso_week)
            ),
            confirmed_days=len(await self._confirmations.confirmed_dates(iso_week)),
            majority_off_plan=_is_majority_off_plan(span, off_plan),
        )


def _measured(row: BlockOutcomeRecord, document: PlanDocument | None) -> Measurement | None:
    """One outcome against the duration its plan of record placed, or nothing if it is not evidence.

    A zero estimate is not a divisor, and a block with no Area carries no minutes to charge
    anywhere: the frame defines how much time exists rather than competing for it, and an anchor is
    time the product does not own.
    """
    if document is None:
        return None
    block = document.blocks_by_id().get(row.block_id)
    actual = row.actual_minutes
    if block is None or actual is None or block.area_id is None:
        return None
    estimated = block.interval.total_minutes()
    if estimated <= 0:
        return None
    return Measurement(area_id=block.area_id, estimated_minutes=estimated, actual_minutes=actual)


def _placements(document: PlanDocument) -> PlacementsById:
    return {block.id: block.interval for block in document.blocks}


def _inside_any(instant: datetime, spans: tuple[Interval, ...]) -> bool:
    return any(span.start <= instant < span.end for span in spans)


def _is_majority_off_plan(span: Interval, off_plan: tuple[Interval, ...]) -> bool:
    """Whether more than half this week's minutes fall inside a declared off-plan span."""
    covered = sum(
        clipped.total_minutes() for one in off_plan if (clipped := one.clipped_to(span)) is not None
    )
    return covered * 2 > span.total_minutes()


def _complete_weeks(now: datetime, *, count: int, profile: ZoneProfile) -> tuple[IsoWeek, ...]:
    """The ``count`` complete ISO weeks before the one ``now`` falls in, oldest first."""
    newest = _last_complete_week(now, profile=profile)
    walked = [newest]
    for _ in range(count - 1):
        walked.append(walked[-1].preceding())
    return tuple(reversed(walked))


def _last_complete_week(now: datetime, *, profile: ZoneProfile) -> IsoWeek:
    """The newest week whose span has ENDED, in the user's own zones.

    Walked rather than subtracted, because the week ``now``'s UTC date falls in is not always the
    week the user is in: a zone west of UTC is still in the previous week for part of a Monday, and
    one east of it is already in the next. At most two steps.
    """
    candidate = IsoWeek.containing(now.date())
    while week_span(candidate, profile).end > now:
        candidate = candidate.preceding()
    return candidate
