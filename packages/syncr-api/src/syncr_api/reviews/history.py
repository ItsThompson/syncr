"""The reviewed quarter, read from the plan of record and the outcome log.

**The denominator is the plan of record's own stored figure.** ``PlanDocument`` carries
``discretionary_minutes`` as the assembler computed it, over all four subtrahends and including
the preceding week's boundary-crossing frame overhang, and that figure is authoritative: the
document's docstring says so and every scalar column beside it is derived from it.

That choice is the reason this module reads a document rather than recomputing a denominator, and
it is deliberate rather than incidental. Recomputing one needs the frame, the anchors, the
absolutely forbidden windows and the overhang assembled again on a read path; the
reader which would do it understates by the whole circadian frame today and a
document-only recomputation overstates by the overhang. Reading the stored figure has neither
error, because it is the figure the week was solved against.

**A week with no plan of record has no denominator, and says so.** ``discretionary_minutes`` is
``None`` there rather than the week's whole span. A week nobody planned holds no confirmed day
either, so it contributes nothing to the review, and reporting its span as discretionary time
would put 168 hours of vacancy on a pie for a user who has not built a day shape yet.

**One outcome read and one off-plan read for the whole quarter.** Both tables are addressed by
span, so the quarter is one span, and the per-week and per-day answers are projections of the two
results. A read per week would be twenty-six statements for the same rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.outcomes.days import blocks_of_the_day, day_span
from syncr_api.outcomes.ledger import settled_at
from syncr_api.plans.stored_documents import plan_document
from syncr_api.reviews.coverage import (
    ReviewedDay,
    confirmed_coverage,
    day_counts,
    is_covered_by,
)
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.weeks import week_span

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_api.plans.reality import BlockOutcomeRepository
    from syncr_api.plans.records import BlockOutcomeRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.reviews.coverage import DayCounts
    from syncr_domain.identifiers import AreaId
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneProfile


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedWeek:
    """One week of the reviewed quarter: what it planned, what it held, and what was answered for.

    ``discretionary_minutes`` is the plan of record's own figure, or ``None`` when the week holds no
    plan. ``covered`` maps an Area to the intervals its blocks really occupied on the confirmed days
    of this week, off-plan spans already removed.

    ``outcomes`` is the log's own rows for this week's blocks, keyed by block id. The pie review
    does not read it: ``covered`` is the aggregate that review wants. The weekly session does,
    because a chronic skip is a run of weeks in which one item was PROPOSED and SKIPPED, which is a
    per-block state rather than an Area total, and both readings have to come from one read of the
    log or the two could disagree about which day was answered for.
    """

    iso_week: IsoWeek
    span: Interval
    discretionary_minutes: int | None
    days: tuple[ReviewedDay, ...]
    off_plan: IntervalSet
    covered: Mapping[AreaId, IntervalSet]
    outcomes: Mapping[str, BlockOutcomeRecord]

    @property
    def counts(self) -> DayCounts:
        """The three day counts this week reports."""
        return day_counts(self.days)

    @property
    def is_fully_confirmed(self) -> bool:
        """Whether every day of this week that held a block was answered for.

        This is what makes a week contribute to a PROPOSAL. A partly confirmed week has its
        actuals over some days and its denominator over all seven, so its observed share is
        understated by exactly the days nobody answered for, and proposing a budget from that
        figure would read a lapse in confirming as a change in behaviour. Such a week is still
        reported: its day counts are what tell the reader how much of the period the figures rest
        on.

        A week with no confirmed day at all is not fully confirmed, whatever else is true of it, so
        a week nobody planned cannot count as a quarter's worth of evidence by holding nothing.
        """
        return self.counts.confirmed > 0 and self.counts.unconfirmed == 0


class ReviewHistoryReader:
    """Reads a run of ISO weeks against the plans, the outcome log, and the off-plan periods."""

    def __init__(
        self,
        plans: PlanRepository,
        outcomes: BlockOutcomeRepository,
        periods: OffPlanPeriodRepository,
    ) -> None:
        self._plans = plans
        self._outcomes = outcomes
        self._periods = periods

    async def read(
        self, weeks: Sequence[IsoWeek], profile: ZoneProfile
    ) -> tuple[ReviewedWeek, ...]:
        """Each week of ``weeks``, in the order given. Reads only, and writes nothing at all."""
        if not weeks:
            return ()
        spans = {week: week_span(week, profile) for week in weeks}
        whole = Interval(spans[weeks[0]].start, spans[weeks[-1]].end)
        off_plan = IntervalSet(record.interval for record in await self._periods.for_span(whole))
        recorded = {str(row.block_id): row for row in await self._outcomes.for_span(whole)}
        read = []
        for week in weeks:
            read.append(
                await self._week(
                    week,
                    spans[week],
                    off_plan=off_plan,
                    recorded=recorded,
                    profile=profile,
                )
            )
        return tuple(read)

    async def _week(
        self,
        iso_week: IsoWeek,
        span: Interval,
        *,
        off_plan: IntervalSet,
        recorded: Mapping[str, BlockOutcomeRecord],
        profile: ZoneProfile,
    ) -> ReviewedWeek:
        revision = await self._plans.latest(iso_week)
        document = None if revision is None else plan_document(revision.document)
        inside = off_plan.clip(span)
        days = _days_of(iso_week, document, off_plan=inside, recorded=recorded, profile=profile)
        return ReviewedWeek(
            iso_week=iso_week,
            span=span,
            discretionary_minutes=None if document is None else document.discretionary_minutes,
            days=days,
            off_plan=inside,
            covered=confirmed_coverage(days, outcomes=recorded, within=span, off_plan=inside),
            outcomes=_outcomes_of(days, recorded=recorded),
        )


def _outcomes_of(
    days: Sequence[ReviewedDay], *, recorded: Mapping[str, BlockOutcomeRecord]
) -> Mapping[str, BlockOutcomeRecord]:
    """The log's rows for the blocks THIS week planned, out of the whole period's read.

    Narrowed to the week's own blocks rather than handed the whole period, so a per-week rule
    stated over it cannot reach another week's row by iterating the mapping.
    """
    return {
        block_id: row
        for day in days
        for block in day.blocks
        if (row := recorded.get(block_id := str(block.id))) is not None
    }


def _days_of(
    iso_week: IsoWeek,
    document: PlanDocument | None,
    *,
    off_plan: IntervalSet,
    recorded: Mapping[str, BlockOutcomeRecord],
    profile: ZoneProfile,
) -> tuple[ReviewedDay, ...]:
    """The week's seven dates, each with the blocks that begin in it and what was answered for.

    A date the tenant's zones do not hold is passed over rather than reported. ``Pacific/Apia``
    skipped 30 December 2011, and a travel override moving a clock far enough east does the same to
    a date: there is no day to report and nothing to confirm. That is ``outcomes.days``' own rule
    for a range walk, and this is a walk.
    """
    days = []
    for on in iso_week.dates():
        span = day_span(on, profile)
        if span is None:
            continue
        blocks = () if document is None else blocks_of_the_day(document, span)
        days.append(
            ReviewedDay(
                on=on,
                span=span,
                blocks=blocks,
                confirmed_at=settled_at([recorded.get(str(block.id)) for block in blocks]),
                is_off_plan=is_covered_by(span, off_plan),
            )
        )
    return tuple(days)
