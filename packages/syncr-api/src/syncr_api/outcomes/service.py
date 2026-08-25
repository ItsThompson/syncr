"""The outcome service: recording, confirming, backfilling, and the day's read model.

Three rules live here rather than anywhere else. What a settled day IS, and what a day holding no
block is, are ``ledger.py``'s; what a request has to satisfy is ``rules.py``'s.

**Recording never confirms, and confirming never overwrites a recording.** They are two acts on
one row. Marking a block skipped during the day says something about the block; confirming the day
says the user has answered for all of it. A day with a skip on it and no confirmation is therefore
excluded from reviews and from learning, and correcting a state after a confirmation keeps the
instant the day was settled at.

**A block is found through the week the request names.** A block id is a digest of the week and the
binding, so the week cannot be recovered from the id, and the alternative is a walk over every
revision the tenant has stored. The 100 ms budget on the recording route is what makes that a
decision rather than a preference.

**Every write bumps the week input version from the current week onwards, and nothing projected is
stored.** The rotation cursor and outstanding debt are derived from the log on every read, so
correcting a past confirmation re-derives them with no step here: there is no stored value for a
correction to disagree with. Both figures are inputs to weeks the user has NOT yet lived, so the
range is the open-ended one and its floor is the week holding today's local date; a past week is
deliberately not bumped, because its approved revision keeps the inputs it was computed with. What
the bump buys is that a solve already running for a future week fails its conditional write.
``BacklogWideBump`` is the one implementation of those four steps.

``require_scope`` maps the writes to ``plan:write`` and the reads to ``plan:read``. Recording an
outcome is an act on a week rather than plan configuration, which is what separates it from a
template or a budget. As on every other domain route today the check denies nothing over HTTP,
because every route reaching these methods resolves a browser session and a session carries every
scope; it becomes live the first time a bearer credential reaches one of these routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.outcomes.config import BLOCK_RESOURCE, ISO_WEEK_FIELD, UNCONFIRMED_LOOKBACK_DAYS
from syncr_api.outcomes.days import ONE_DAY
from syncr_api.outcomes.ledger import (
    Backfill,
    DayLedger,
    is_unconfirmed,
    ledger_rows,
    settled_at,
    split_at,
)
from syncr_api.outcomes.planned_days import spanning
from syncr_api.outcomes.rules import (
    DATE_FIELD,
    require_a_dated_span,
    require_a_day_that_has_begun,
    require_a_range_that_can_be_confirmed,
    require_a_reportable_interval,
    stated_rejection,
)
from syncr_api.plans.stored_documents import plan_document
from syncr_api.user_settings.zone_reading import as_domain, local_date, zone_profile
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.outcomes import RecordedOutcome
from syncr_domain.zones import active_zone

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.outcomes.declarations import Recording
    from syncr_api.outcomes.planned_days import PlannedDay, PlannedDayReader
    from syncr_api.plans.reality import BlockOutcomeRepository
    from syncr_api.plans.records import BlockOutcomeRecord, PlanRevisionRecord
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_api.user_settings.solve_inputs import BacklogWideBump
    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BlockId
    from syncr_domain.plan import Block
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneProfile

_log = get_logger("syncr.outcomes")


class OutcomeService:
    """One tenant's reality state: what happened to each block, and which days are settled."""

    def __init__(
        self,
        *,
        plans: PlanRepository,
        days: PlannedDayReader,
        outcomes: BlockOutcomeRepository,
        areas: AreaRepository,
        settings: SettingsRepository,
        overrides: TravelOverrideRepository,
        bump: BacklogWideBump,
        clock: Clock,
    ) -> None:
        self._plans = plans
        self._days = days
        self._outcomes = outcomes
        self._areas = areas
        self._settings = settings
        self._overrides = overrides
        self._bump = bump
        self._clock = clock

    @measured("outcomes")
    async def record(
        self, principal: Principal, block_id: BlockId, recording: Recording
    ) -> BlockOutcomeRecord:
        """State what happened to one block, and invalidate the weeks that read the log.

        The binding comes from the block rather than from the request, because it is what the row
        denormalizes and what the re-derivation keys on: a caller that could supply one could
        attribute a fact about one habit to another.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(recording.iso_week, field=ISO_WEEK_FIELD)
        require_a_reportable_interval(recording.actual_interval)
        revision, block = await self._placed(week, block_id)
        with stated_rejection():
            outcome = RecordedOutcome(
                binding=block.binding,
                state=recording.state,
                actual_minutes=recording.actual_minutes,
                actual_interval=recording.actual_interval,
            )

        recorded = await self._outcomes.record(
            outcome,
            block_id=block.id,
            revision_id=revision.id,
            occurred_at=block.interval.start,
            make_up=block.make_up,
        )
        _log.info(
            "outcomes.outcome.recorded",
            tenant_id=str(principal.tenant_id),
            iso_week=str(week),
            block_id=block.id,
            origin=block.origin.value,
            state=recorded.state.value,
            actual_minutes=recorded.actual_minutes,
            moved=recorded.actual_interval is not None,
            confirmed=recorded.is_confirmed,
        )
        await self._bump.from_the_week_holding(self._clock())
        return recorded

    @measured("outcomes")
    async def read_day(self, principal: Principal, on: Date) -> DayLedger:
        """One day's ledger. Writes nothing, and records no presumption."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._ledger(on, profile=await self._profile())

    @measured("outcomes")
    async def confirm_day(self, principal: Principal, on: Date) -> DayLedger:
        """Convert presumption into record for one day, and answer with the settled ledger."""
        require_scope(principal, Scope.PLAN_WRITE)
        profile = await self._profile()
        now = self._clock()
        require_a_day_that_has_begun(on, profile, now, field=DATE_FIELD)

        planned = await self._days.read(on, on, profile)
        recorded = await self._settle(planned, at=now)
        _log.info(
            "outcomes.day.confirmed",
            tenant_id=str(principal.tenant_id),
            date=on.isoformat(),
            blocks_recorded=recorded,
        )
        await self._bump.from_the_week_holding(now)
        return await self._ledger(on, profile=profile, planned=planned)

    @measured("outcomes")
    async def confirm_range(self, principal: Principal, first: Date, last: Date) -> Backfill:
        """Confirm every day from ``first`` to ``last``, and answer with how many it settled.

        Any past day can be confirmed at any later time, and a day settled weeks afterwards counts
        identically to one settled the same evening: the log records what happened and when the
        user answered, and no maturity gate reads the gap between the two.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        profile = await self._profile()
        now = self._clock()
        require_a_range_that_can_be_confirmed(first, last, profile, now)

        planned = await self._days.read(first, last, profile)
        outstanding = await self._outstanding(planned)
        recorded = await self._settle(outstanding, at=now)
        _log.info(
            "outcomes.days.backfilled",
            tenant_id=str(principal.tenant_id),
            first_date=first.isoformat(),
            last_date=last.isoformat(),
            days_confirmed=len(outstanding),
            blocks_recorded=recorded,
        )
        await self._bump.from_the_week_holding(now)
        return Backfill(
            days=len(outstanding),
            blocks=recorded,
            unconfirmed_days=await self._unconfirmed_days(profile, now),
        )

    async def _profile(self) -> ZoneProfile:
        """The tenant's zones, which is what decides how long each of their days is."""
        return zone_profile(
            (await self._settings.read()).home_zone, as_domain(await self._overrides.list_all())
        )

    async def _ledger(
        self, on: Date, *, profile: ZoneProfile, planned: Sequence[PlannedDay] | None = None
    ) -> DayLedger:
        """One day's rows, its header figures, and how many days are outstanding.

        The span is required first, so a date the tenant's zones do not hold is refused before any
        read: the alternative is an empty ledger, which reads as a day with no plan.

        ``planned`` is passed by a caller that has already read the day, which is what stops a
        confirmation reading the same revision twice on a path with a 400 ms budget.
        """
        now = self._clock()
        span = require_a_dated_span(on, profile, field=DATE_FIELD)
        held = planned if planned is not None else await self._days.read(on, on, profile)
        blocks = held[0].blocks if held else ()
        recorded = {row.block_id: row for row in await self._outcomes.for_span(span)}
        rows = ledger_rows(blocks, outcomes=recorded, area_names=await self._area_names())
        behind, ahead = split_at(rows, now)
        return DayLedger(
            on=on,
            zone=active_zone(profile, on),
            span=span,
            behind=behind,
            ahead=ahead,
            confirmed_at=settled_at([row.outcome for row in rows]),
            unconfirmed_days=await self._unconfirmed_days(profile, now),
        )

    async def _outstanding(self, planned: Sequence[PlannedDay]) -> tuple[PlannedDay, ...]:
        """The days of a range that hold blocks and have not been answered for.

        One read of the whole range's outcomes rather than one per day: the rows are keyed by block,
        so which day each belongs to is decided by the blocks the day holds.
        """
        window = spanning(planned)
        if window is None:
            return ()
        recorded = {row.block_id: row for row in await self._outcomes.for_span(window)}
        return tuple(
            day
            for day in planned
            if is_unconfirmed([recorded.get(block.id) for block in day.blocks])
        )

    async def _settle(self, planned: Sequence[PlannedDay], *, at: datetime) -> int:
        """Record every block of these days, and answer how many rows it settled."""
        return await self._outcomes.settle(
            [one for day in planned for one in day.presumptions()], at=at
        )

    async def _unconfirmed_days(self, profile: ZoneProfile, now: datetime) -> int:
        """How many days behind ``now`` hold blocks and have not been answered for.

        Bounded at the lookback window, and the bound is on the COUNT rather than on the act: a day
        older than the window is still confirmable by naming it. Today is excluded, because a day
        the user is still living is not one they have failed to answer for.
        """
        today = local_date(now, profile.home_zone)
        first = today - ONE_DAY * UNCONFIRMED_LOOKBACK_DAYS
        return len(await self._outstanding(await self._days.read(first, today - ONE_DAY, profile)))

    async def _area_names(self) -> Mapping[AreaId, str]:
        """The Areas' names, for the chip each row renders."""
        return {area.id: area.name for area in await self._areas.list_all()}

    async def _placed(self, week: IsoWeek, block_id: BlockId) -> tuple[PlanRevisionRecord, Block]:
        """The plan of record holding that block and the block itself, or a 404.

        A week with no plan and a week whose plan does not hold the block are one answer, because
        both say the same thing to a caller: nothing in that week has that identity. Disclosing
        which of the two it is would say whether the week has been solved, which is not this
        route's business.
        """
        revision = await self._plans.latest(week)
        found = (
            None
            if revision is None
            else plan_document(revision.document).blocks_by_id().get(block_id)
        )
        if revision is None or found is None:
            raise NotFound(
                f"No {BLOCK_RESOURCE} of that week matches that identifier. Nothing was changed. A "
                "block id is derived from the week and the content it holds, so a re-solve that "
                "dropped the content leaves the id naming nothing."
            )
        return (revision, found)
